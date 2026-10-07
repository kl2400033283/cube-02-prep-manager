"""Evidence integrity, append-only overrides and tenant isolation (Rule 1)."""

import sqlite3
import unittest

from _helpers import make_agent, scenario_input
from submissions.kl2400033283.agent.db.database import TenantAccessDeniedError


class TestEvidence(unittest.TestCase):
    def setUp(self):
        self.agent = make_agent()
        self.rec = self.agent.inspect(scenario_input("fnsku-on-seam"))

    def test_any_field_change_breaks_the_seal(self):
        stored = self.agent.db.get_evidence_record("org_demo_alpha", self.rec.record_id)
        self.assertTrue(stored.verify_integrity())
        for mutate in (lambda r: setattr(r.checks[2], "confidence", 0.01),
                       lambda r: setattr(r.checks[2], "detail", "edited"),
                       lambda r: setattr(r.outcome, "summary", "PASS"),
                       lambda r: setattr(r.images[0], "sha256_digest", "0" * 64)):
            r = stored.model_copy(deep=True)
            mutate(r)
            self.assertFalse(r.verify_integrity())

    def test_override_requires_reason_and_keeps_original(self):
        with self.assertRaises(ValueError):
            self.agent.apply_override("org_demo_alpha", self.rec.record_id, "fnsku_label_placement", "PASS", "  ", "op1",
                                      role="supervisor")
        upd = self.agent.apply_override("org_demo_alpha", self.rec.record_id, "fnsku_label_placement", "PASS",
                                        "Relabelled on flat panel at bench 2", "sup_dana", role="supervisor")
        o = upd.overrides[-1]
        self.assertEqual(o.original_verdict.value, "FAIL")
        self.assertEqual(o.direction, "relax")
        self.assertEqual(o.previous_content_hash, self.rec.content_hash)
        self.assertEqual(o.new_content_hash, upd.content_hash)
        self.assertTrue(upd.verify_integrity())
        self.assertEqual(upd.outcome.decided_by, "supervisor:sup_dana")
        original = self.agent.db.get_original_record("org_demo_alpha", self.rec.record_id)
        self.assertEqual(original.content_hash, self.rec.content_hash)  # original untouched
        self.assertTrue(self.agent.db.verify("org_demo_alpha", self.rec.record_id)["integrity_verified"])

    def test_operator_cannot_relax_a_fail(self):
        from submissions.kl2400033283.agent.core.prep_agent import OverridePermissionError
        with self.assertRaises(OverridePermissionError):
            self.agent.apply_override("org_demo_alpha", self.rec.record_id, "fnsku_label_placement", "PASS",
                                      "looks fine to me", "op1", role="operator")
        # tightening is allowed for an operator
        upd = self.agent.apply_override("org_demo_alpha", self.rec.record_id, "handling_marks", "FAIL",
                                        "FRAGILE sticker peeling", "op1", role="operator")             if any(c.check_key == "handling_marks" and c.verdict.value == "PASS" for c in self.rec.checks) else None
        if upd:
            self.assertEqual(upd.overrides[-1].direction, "tighten")

    def test_override_chain_links(self):
        a = self.agent.apply_override("org_demo_alpha", self.rec.record_id, "fnsku_label_placement", "UNCERTAIN",
                                      "needs QA look", "sup1", role="supervisor")
        b = self.agent.apply_override("org_demo_alpha", self.rec.record_id, "fnsku_label_placement", "PASS",
                                      "QA relabelled", "sup2", role="supervisor")
        self.assertEqual(b.overrides[1].previous_content_hash, a.content_hash)
        v = self.agent.db.verify("org_demo_alpha", self.rec.record_id)
        self.assertTrue(v["integrity_verified"], v["problems"])
        self.assertEqual(v["seal_chain_length"], 3)

    def test_stale_override_is_rejected(self):
        from submissions.kl2400033283.agent.db.database import ConcurrentOverrideError
        h0 = self.rec.content_hash
        self.agent.apply_override("org_demo_alpha", self.rec.record_id, "fnsku_label_placement", "UNCERTAIN",
                                  "first reviewer", "sup1", role="supervisor", expected_content_hash=h0)
        with self.assertRaises(ConcurrentOverrideError):
            self.agent.apply_override("org_demo_alpha", self.rec.record_id, "fnsku_label_placement", "PASS",
                                      "second reviewer, stale view", "sup2", role="supervisor", expected_content_hash=h0)

    def test_tables_are_append_only_at_db_level(self):
        self.agent.apply_override("org_demo_alpha", self.rec.record_id, "fnsku_label_placement", "PASS", "relabelled",
                                  "sup1", role="supervisor")
        conn = sqlite3.connect(str(self.agent.db.db_path))
        for sql in ("UPDATE overrides SET reason = 'tampered'", "DELETE FROM overrides",
                    "UPDATE prep_records SET payload_json = '{}'", "DELETE FROM prep_records",
                    "UPDATE seals SET mac = 'x'", "DELETE FROM seals"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                conn.execute(sql)
        conn.close()

    def test_editing_current_state_is_detected_even_with_recomputed_hash(self):
        stored = self.agent.db.get_evidence_record("org_demo_alpha", self.rec.record_id)
        forged = stored.model_copy(deep=True)
        for c in forged.checks:
            if c.verdict.value == "FAIL":
                c.verdict = type(c.verdict)("PASS")
        forged.outcome.summary = "TAMPERED_PASS"
        forged.content_hash = forged.compute_content_hash()  # attacker recomputes the plain SHA-256
        conn = sqlite3.connect(str(self.agent.db.db_path))
        conn.execute("UPDATE record_state SET content_hash = ?, payload_json = ?, decision = 'PASS' WHERE record_id = ?",
                     (forged.content_hash, forged.model_dump_json(), self.rec.record_id))
        conn.commit()
        conn.close()
        v = self.agent.db.verify("org_demo_alpha", self.rec.record_id)
        self.assertFalse(v["integrity_verified"])
        self.assertTrue(any("state" in p for p in v["problems"]))

    def test_forged_seal_without_key_is_detected(self):
        conn = sqlite3.connect(str(self.agent.db.db_path))
        conn.execute("DROP TRIGGER seals_no_update")  # attacker with full DB access, but no seal key
        conn.execute("UPDATE seals SET content_hash = ? WHERE record_id = ?", ("f" * 64, self.rec.record_id))
        conn.commit()
        conn.close()
        v = self.agent.db.verify("org_demo_alpha", self.rec.record_id)
        self.assertFalse(v["integrity_verified"])
        self.assertTrue(any("MAC" in p for p in v["problems"]))

    def test_persistence_failure_is_flagged_and_spooled(self):
        agent = make_agent()

        def boom(_record):
            raise sqlite3.OperationalError("disk I/O error")
        agent.db.save_new_record = boom
        rec = agent.inspect(scenario_input("correct-prep"))
        self.assertIs(rec.persisted, False)
        self.assertTrue((agent.db.spool_dir / "org_demo_alpha" / f"{rec.record_id}.json").exists())
        del agent.db.save_new_record  # restore the real method, then replay
        self.assertEqual(agent.db.replay_spool(), 1)
        self.assertIsNotNone(agent.db.get_evidence_record("org_demo_alpha", rec.record_id))

    def test_unknown_check_key_rejected(self):
        with self.assertRaises(ValueError):
            self.agent.apply_override("org_demo_alpha", self.rec.record_id, "made_up_check", "PASS", "reason", "op1")


class TestTenancy(unittest.TestCase):
    def setUp(self):
        self.agent = make_agent()
        self.a = self.agent.inspect(scenario_input("correct-prep", org="org_demo_alpha"))
        self.b = self.agent.inspect(scenario_input("barcode-visible", org="org_demo_bravo"))

    def test_records_invisible_across_tenants(self):
        db = self.agent.db
        self.assertIsNone(db.get_evidence_record("org_demo_bravo", self.a.record_id))
        self.assertIsNone(db.get_evidence_record("org_demo_alpha", self.b.record_id))
        self.assertNotIn(self.a.record_id, [r["record_id"] for r in db.list_records("org_demo_bravo")])
        self.assertEqual(db.cross_tenant_leakage_rows("org_demo_alpha", "org_demo_bravo"), 0)
        self.assertEqual(db.cross_tenant_leakage_rows("org_demo_bravo", "org_demo_alpha"), 0)

    def test_cannot_override_another_tenants_record(self):
        with self.assertRaises(TenantAccessDeniedError):
            self.agent.apply_override("org_demo_bravo", self.a.record_id, "handling_marks", "FAIL", "attack", "evil",
                                      role="supervisor")

    def test_unknown_tenant_rejected(self):
        with self.assertRaises(TenantAccessDeniedError):
            self.agent.inspect(scenario_input("correct-prep", org="org_evil"))
        with self.assertRaises(TenantAccessDeniedError):
            self.agent.db.list_records("org_evil")

    def test_assets_scoped_to_tenant(self):
        aid = self.agent.db.save_asset("org_demo_alpha", b"x" * 200, "ab" * 32, "image/jpeg", ".jpg")
        self.assertIsNotNone(self.agent.db.get_asset("org_demo_alpha", aid))
        self.assertIsNone(self.agent.db.get_asset("org_demo_bravo", aid))

    def test_metrics_are_tenant_scoped(self):
        self.assertEqual(self.agent.db.metrics("org_demo_alpha")["total_units"], 1)
        self.assertEqual(self.agent.db.metrics("org_demo_bravo")["decisions"]["FAIL"], 1)


if __name__ == "__main__":
    unittest.main()
