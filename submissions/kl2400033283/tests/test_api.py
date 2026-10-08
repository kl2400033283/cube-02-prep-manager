"""HTTP API: authentication, tenant derivation, signed media, upload validation, headers, flows."""

import io
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from _helpers import make_agent, temp_db
from submissions.kl2400033283.agent import api as api_module

A = {"X-API-Key": "alpha-demo-key"}
B = {"X-API-Key": "bravo-demo-key"}
SUP = {"X-API-Key": "alpha-supervisor-key"}


def png_bytes(size=(400, 300)):
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 80, 60)).save(buf, format="PNG")
    return buf.getvalue()


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = temp_db()
        api_module.db = db
        api_module.agent = make_agent(db=db)
        cls.c = TestClient(api_module.app)

    def inspect(self, headers=A, **body):
        payload = {"unit_id": "UNIT-API-1", "scenario_id": "fnsku-on-seam", "category": "general"}
        payload.update(body)
        return self.c.post("/api/v1/inspections", json=payload, headers=headers)

    def test_public_endpoints(self):
        for path in ("/api/v1/health", "/api/v1/agent", "/api/v1/rules", "/api/v1/categories", "/api/v1/scenarios", "/",
                     "/openapi.json", "/docs"):
            self.assertEqual(self.c.get(path).status_code, 200, path)
        self.assertEqual(len(self.c.get("/api/v1/agent").json()["description"]), 2)

    def test_auth_required_and_tenant_comes_from_key(self):
        self.assertEqual(self.c.get("/api/v1/records").status_code, 401)
        self.assertEqual(self.c.get("/api/v1/records", headers={"X-API-Key": "nope-nope"}).status_code, 401)
        # A client-supplied org header is ignored: the key decides.
        r = self.inspect(headers={**B, "X-Org-Id": "org_demo_alpha"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["record"]["organization_id"], "org_demo_bravo")

    def test_inspection_and_cross_tenant_404(self):
        r = self.inspect()
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertTrue(body["integrity_verified"])
        rid = body["record"]["record_id"]
        self.assertEqual(body["record"]["outcome"]["decision"], "FAIL")
        self.assertEqual(self.c.get(f"/api/v1/records/{rid}", headers=A).status_code, 200)
        self.assertEqual(self.c.get(f"/api/v1/records/{rid}", headers=B).status_code, 404)
        self.assertEqual(self.c.get(f"/api/v1/records/{rid}/verify", headers=A).json()["integrity_verified"], True)

    def test_extra_fields_and_bad_values_rejected(self):
        self.assertEqual(self.inspect(image_paths=["C:/Windows/win.ini"]).status_code, 422)  # no raw paths, ever
        self.assertEqual(self.inspect(unit_id="../../etc/passwd").status_code, 422)
        self.assertEqual(self.inspect(category="not_a_category").status_code, 422)
        self.assertEqual(self.inspect(scenario_id=None, asset_ids=["deadbeef"]).status_code, 404)

    def test_signed_media_urls(self):
        body = self.inspect().json()
        url = body["image_urls"][0]
        self.assertEqual(self.c.get(url).status_code, 200)
        self.assertEqual(self.c.get(url.replace("org_demo_alpha", "org_demo_bravo")).status_code, 403)
        self.assertEqual(self.c.get(url[:-4] + "0000").status_code, 403)
        self.assertEqual(self.c.get(url.replace("exp=", "exp=1")).status_code, 403)

    def test_upload_validation_and_tenant_scoped_assets(self):
        bad = self.c.post("/api/v1/assets", files={"file": ("x.jpg", b"<script>alert(1)</script>" * 20, "image/jpeg")}, headers=A)
        self.assertEqual(bad.status_code, 400)
        tiny = self.c.post("/api/v1/assets", files={"file": ("x.png", png_bytes((50, 50)), "image/png")}, headers=A)
        self.assertEqual(tiny.status_code, 400)
        ok = self.c.post("/api/v1/assets", files={"file": ("p.png", png_bytes(), "image/png")}, headers=A)
        self.assertEqual(ok.status_code, 201)
        aid = ok.json()["asset_id"]
        self.assertEqual(self.inspect(scenario_id=None, asset_ids=[aid]).status_code, 201)
        self.assertEqual(self.inspect(headers=B, scenario_id=None, asset_ids=[aid]).status_code, 404)

    def test_override_and_dispute_packet(self):
        rid = self.inspect().json()["record"]["record_id"]
        body = {"check_key": "fnsku_label_placement", "new_verdict": "PASS", "reason": "relabelled at bench"}
        r = self.c.post(f"/api/v1/records/{rid}/overrides", headers=SUP, json={**body, "reason": "x"})
        self.assertEqual(r.status_code, 422)  # reason too short
        r = self.c.post(f"/api/v1/records/{rid}/overrides", headers=A, json=body)
        self.assertEqual(r.status_code, 403)  # an operator may not relax FAIL -> PASS
        r = self.c.post(f"/api/v1/records/{rid}/overrides", headers=SUP, json={**body, "operator_id": "someone_else"})
        self.assertEqual(r.status_code, 200)
        o = r.json()["record"]["overrides"][-1]
        self.assertEqual((o["operator_id"], o["role"]), ("sup_alpha", "supervisor"))  # identity from the key
        stale = self.c.post(f"/api/v1/records/{rid}/overrides", headers=SUP,
                            json={**body, "new_verdict": "UNCERTAIN", "expected_content_hash": "0" * 64})
        self.assertEqual(stale.status_code, 409)
        v = self.c.get(f"/api/v1/records/{rid}/verify", headers=A).json()
        self.assertTrue(v["integrity_verified"], v["problems"])
        self.assertEqual(v["seal_chain_length"], 2)
        pkt = self.c.get(f"/api/v1/records/{rid}/dispute-packet", headers=A).json()
        self.assertTrue(pkt["integrity_verified"])
        self.assertEqual(pkt["consumer"], "agent_05_recovery")
        self.assertEqual(len(pkt["overrides"]), 1)
        fnsku = next(st for st in pkt["statements"] if st["check_key"] == "fnsku_label_placement")
        self.assertEqual(fnsku["agent_verdict"], "FAIL")
        self.assertFalse(fnsku["usable_as_defense"])  # a human-made PASS is not agent evidence

    def test_client_cannot_claim_calibration_or_mix_sources(self):
        self.assertEqual(self.inspect(station_calibrated=True).status_code, 422)  # field no longer exists
        ok = self.c.post("/api/v1/assets", files={"file": ("p.png", png_bytes(), "image/png")}, headers=A).json()
        self.assertEqual(self.inspect(asset_ids=[ok["asset_id"]]).status_code, 422)  # scenario + asset

    def test_upload_strips_exif_and_rejects_oversize(self):
        im = Image.new("RGB", (400, 300), (10, 120, 200))
        exif = Image.Exif()
        exif[0x010F] = "SecretCam"   # Make
        exif[0x0112] = 6             # Orientation: rotate 90
        buf = io.BytesIO()
        im.save(buf, format="JPEG", exif=exif.tobytes())
        r = self.c.post("/api/v1/assets", files={"file": ("e.jpg", buf.getvalue(), "image/jpeg")}, headers=A)
        self.assertEqual(r.status_code, 201)
        j = r.json()
        self.assertTrue(j["metadata_stripped"])
        self.assertNotEqual(j["sha256"], j["original_sha256"])
        self.assertEqual((j["width"], j["height"]), (300, 400))  # orientation applied
        stored = self.c.get(j["preview_url"]).content
        self.assertNotIn(b"SecretCam", stored)
        with Image.open(io.BytesIO(stored)) as back:
            self.assertEqual(len(back.getexif()), 0)
        from submissions.kl2400033283.agent.config import MAX_UPLOAD_BYTES
        big = bytes([255]) * (MAX_UPLOAD_BYTES + 10)
        self.assertEqual(self.c.post("/api/v1/assets", files={"file": ("b.jpg", big, "image/jpeg")}, headers=A).status_code, 413)

    def test_security_headers(self):
        h = self.c.get("/api/v1/health").headers
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        self.assertIn("X-Request-ID", h)

    def test_fail_open_drill_and_audit(self):
        r = self.c.post("/api/v1/drills/fail-open", headers=A, json={"fault": "provider_error"}).json()
        self.assertEqual(r["record"]["outcome"]["decision"], "PENDING_REVIEW")
        a = self.c.get("/api/v1/tenancy/audit", headers=A).json()
        self.assertTrue(a["isolation_verified"])
        self.assertEqual(a["cross_tenant_rows_visible"], 0)

    def test_metrics_shape(self):
        self.inspect()
        m = self.c.get("/api/v1/metrics", headers=A).json()
        for k in ("total_units", "decisions", "effective_decisions", "latency_ms", "per_check",
                  "effective_per_check", "avg_cost_usd"):
            self.assertIn(k, m)


if __name__ == "__main__":
    unittest.main()
