"""Tenant-scoped persistence (SQLite) with an immutable original record and a keyed seal chain.

Engineering Rule 1 - tenancy before features: every table carries ``org_id`` and every query
filters on it; there is no method that reads or writes without an org_id argument.

Evidence integrity (what is - and is not - claimed):
* ``prep_records`` holds the ORIGINAL record exactly as the agent produced it. SQLite triggers
  reject UPDATE and DELETE, so application code cannot rewrite it.
* ``seals`` is append-only (triggers). Seal 0 covers the original; seal n covers the record after
  override n. Each seal is HMAC-SHA256(key, org|record|seq|kind|content_hash|prev_mac) with the
  key held outside the database, so an attacker who can edit the DB but cannot read the key
  cannot produce a valid seal for altered content.
* ``overrides`` is append-only. ``record_state`` is only a cache of the effective (overridden)
  record for fast reads; ``verify()`` never trusts it - it replays original + overrides and checks
  every hash and every MAC, and that the cache matches the end of the chain.
* Limits (documented honestly): someone holding both DB write access and the key file can still
  forge; a production deployment keeps the key in a KMS/HSM and anchors seal hashes externally.
"""

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from submissions.kl2400033283.agent.config import ALLOWED_ORGS, DB_PATH, UPLOAD_DIR
from submissions.kl2400033283.agent.core.overrides import (
    apply_override, check_mac, make_mac, seal_info,
)
from submissions.kl2400033283.agent.schemas.evidence import EvidenceRecord, OverallDecisionEnum, OverrideEntry


class TenantAccessDeniedError(PermissionError):
    """Raised when an operation targets data outside the caller's tenant."""


class ConcurrentOverrideError(RuntimeError):
    """The record changed since the caller read it (compare-and-swap on the content hash failed)."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS prep_records (
    org_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (org_id, record_id)
);
CREATE TRIGGER IF NOT EXISTS prep_records_no_update BEFORE UPDATE ON prep_records
BEGIN SELECT RAISE(ABORT, 'original evidence records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prep_records_no_delete BEFORE DELETE ON prep_records
BEGIN SELECT RAISE(ABORT, 'original evidence records are immutable'); END;

CREATE TABLE IF NOT EXISTS record_state (
    org_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    category TEXT,
    decision TEXT NOT NULL,
    dispatch TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT,
    cost_usd REAL DEFAULT 0,
    total_latency_ms REAL DEFAULT 0,
    captured_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (org_id, record_id),
    FOREIGN KEY (org_id, record_id) REFERENCES prep_records(org_id, record_id)
);
CREATE INDEX IF NOT EXISTS idx_state_org_time ON record_state(org_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_state_org_unit ON record_state(org_id, unit_id);

CREATE TABLE IF NOT EXISTS seals (
    org_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    prev_mac TEXT NOT NULL,
    mac TEXT NOT NULL,
    key_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, record_id, seq),
    FOREIGN KEY (org_id, record_id) REFERENCES prep_records(org_id, record_id)
);
CREATE TRIGGER IF NOT EXISTS seals_no_update BEFORE UPDATE ON seals
BEGIN SELECT RAISE(ABORT, 'seals are append-only'); END;
CREATE TRIGGER IF NOT EXISTS seals_no_delete BEFORE DELETE ON seals
BEGIN SELECT RAISE(ABORT, 'seals are append-only'); END;

CREATE TABLE IF NOT EXISTS check_verdicts (
    org_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    check_key TEXT NOT NULL,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason_code TEXT,
    PRIMARY KEY (org_id, record_id, check_key),
    FOREIGN KEY (org_id, record_id) REFERENCES prep_records(org_id, record_id)
);

CREATE TABLE IF NOT EXISTS overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    entry_json TEXT NOT NULL,
    check_key TEXT NOT NULL,
    original_verdict TEXT NOT NULL,
    new_verdict TEXT NOT NULL,
    reason TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    role TEXT NOT NULL,
    overridden_at TEXT NOT NULL,
    previous_content_hash TEXT NOT NULL,
    new_content_hash TEXT NOT NULL,
    UNIQUE (org_id, record_id, seq),
    FOREIGN KEY (org_id, record_id) REFERENCES prep_records(org_id, record_id)
);
CREATE TRIGGER IF NOT EXISTS overrides_no_update BEFORE UPDATE ON overrides
BEGIN SELECT RAISE(ABORT, 'overrides are append-only'); END;
CREATE TRIGGER IF NOT EXISTS overrides_no_delete BEFORE DELETE ON overrides
BEGIN SELECT RAISE(ABORT, 'overrides are append-only'); END;

CREATE TABLE IF NOT EXISTS assets (
    org_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    original_sha256 TEXT,
    storage_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, asset_id)
);

CREATE TABLE IF NOT EXISTS pod_requests (
    org_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    output_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, request_id)
);
CREATE TRIGGER IF NOT EXISTS pod_requests_no_update BEFORE UPDATE ON pod_requests
BEGIN SELECT RAISE(ABORT, 'pod outputs are immutable'); END;
"""


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TenantDatabase:
    def __init__(self, db_file: Optional[Path] = None, upload_dir: Optional[Path] = None,
                 spool_dir: Optional[Path] = None):
        self.db_path = Path(db_file or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir = Path(upload_dir or UPLOAD_DIR)
        self.spool_dir = Path(spool_dir or (self.db_path.parent / "spool"))
        self._lock = threading.Lock()
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        try:
            legacy = self._archive_legacy_schema(conn)
            conn.executescript(SCHEMA)  # executescript manages its own transaction
            self._add_missing_columns(conn)
        finally:
            conn.close()
        if legacy:
            self._import_legacy(legacy)

    # Columns added after a table first shipped: CREATE TABLE IF NOT EXISTS does not add them to an
    # existing database, so add them here (nullable, so old rows stay valid).
    _ADDED_COLUMNS = {"assets": [("original_sha256", "TEXT")]}

    @classmethod
    def _add_missing_columns(cls, conn) -> None:
        for table, cols in cls._ADDED_COLUMNS.items():
            have = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            for name, kind in cols:
                if name not in have:
                    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {name} {kind}')
        conn.commit()

    # ------------------------------------------------------------------ migration from the v2.0 layout
    _LEGACY_TABLES = ("prep_records", "check_verdicts", "overrides", "original_seals")
    _NEW_ONLY = ("record_state", "seals", "pod_requests")

    @classmethod
    def _archive_legacy_schema(cls, conn) -> Optional[str]:
        """v2.0 stored a mutable prep_records (with a 'decision' column). Keep those tables as a
        read-only archive (legacy_v20_*) and let the new schema be created next to them."""
        cols = [r[1] for r in conn.execute("PRAGMA table_info(prep_records)")]
        if not cols or "decision" not in cols:
            return None
        conn.execute("PRAGMA legacy_alter_table = ON")  # do not rewrite references in other tables
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
            conn.execute(f'DROP TRIGGER IF EXISTS "{name}"')
        for t in cls._NEW_ONLY:  # created empty by a half-applied upgrade: recreate cleanly
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
            if exists and conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] == 0:
                conn.execute(f'DROP TABLE "{t}"')
        for t in cls._LEGACY_TABLES:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
                conn.execute(f'ALTER TABLE "{t}" RENAME TO "legacy_v20_{t}"')
        conn.commit()
        return "legacy_v20_prep_records"

    def _import_legacy(self, table: str) -> None:
        """Re-seal archived records in the new schema so the console history survives. The seal then
        attests the content as of the migration, not as of capture (the archive table is kept)."""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        try:
            rows = conn.execute(f'SELECT payload_json FROM "{table}"').fetchall()
        finally:
            conn.close()
        for (payload,) in rows:
            try:
                rec = EvidenceRecord.model_validate_json(payload)
                if rec.organization_id in ALLOWED_ORGS:
                    self.save_new_record(rec)
            except Exception:
                continue

    @contextmanager
    def _conn(self, immediate: bool = False):
        conn = sqlite3.connect(str(self.db_path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @staticmethod
    def _require_org(org_id: str):
        if org_id not in ALLOWED_ORGS:
            raise TenantAccessDeniedError(f"Unknown tenant: {org_id}")

    # ------------------------------------------------------------------ write: new record
    def save_new_record(self, record: EvidenceRecord) -> None:
        org = record.organization_id
        self._require_org(org)
        record.content_hash = record.compute_content_hash()
        mac = make_mac(org, record.record_id, 0, "original", record.content_hash, "")
        record.seal = seal_info(0, "original", mac)
        with self._lock, self._conn(immediate=True) as c:
            c.execute("INSERT INTO prep_records (org_id, record_id, unit_id, captured_at, content_hash, payload_json)"
                      " VALUES (?,?,?,?,?,?)",
                      (org, record.record_id, record.subject.unit_id, record.captured_at, record.content_hash,
                       record.model_dump_json(exclude={"seal", "persisted"})))
            c.execute("INSERT INTO seals (org_id, record_id, seq, kind, content_hash, prev_mac, mac, key_id, created_at)"
                      " VALUES (?,?,?,?,?,?,?,?,?)",
                      (org, record.record_id, 0, "original", record.content_hash, "", mac, record.seal["key_id"], _now()))
            self._write_state(c, record, version=0)
        record.persisted = True

    @staticmethod
    def _write_state(c, record: EvidenceRecord, version: int) -> None:
        org = record.organization_id
        c.execute(
            "INSERT OR REPLACE INTO record_state (org_id, record_id, unit_id, category, decision, dispatch, status, provider,"
            " cost_usd, total_latency_ms, captured_at, content_hash, version, payload_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (org, record.record_id, record.subject.unit_id, record.subject.category, record.outcome.decision.value,
             record.outcome.dispatch.value, record.status.value,
             record.perception.provider if record.perception else None,
             record.perception.cost_usd if record.perception else 0.0,
             record.total_latency_ms, record.captured_at, record.content_hash, version,
             record.model_dump_json(exclude={"persisted"})))
        c.execute("DELETE FROM check_verdicts WHERE org_id = ? AND record_id = ?", (org, record.record_id))
        c.executemany(
            "INSERT INTO check_verdicts (org_id, record_id, check_key, verdict, confidence, reason_code) VALUES (?,?,?,?,?,?)",
            [(org, record.record_id, ch.check_key, ch.verdict.value, ch.confidence, ch.reason_code) for ch in record.checks])

    # ------------------------------------------------------------------ persistence fallback
    def spool(self, record: EvidenceRecord) -> Path:
        """Write a record that could not be stored to a spool file for later replay (never lost)."""
        folder = self.spool_dir / record.organization_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{record.record_id}.json"
        path.write_text(record.model_dump_json(exclude={"seal", "persisted"}), encoding="utf-8")
        return path

    def replay_spool(self) -> int:
        n = 0
        if not self.spool_dir.exists():
            return 0
        for f in sorted(self.spool_dir.glob("*/*.json")):
            try:
                rec = EvidenceRecord.model_validate_json(f.read_text(encoding="utf-8"))
                self.save_new_record(rec)
                f.unlink()
                n += 1
            except sqlite3.IntegrityError:
                f.unlink()  # already stored
            except Exception:
                continue
        return n

    # ------------------------------------------------------------------ reads
    def get_evidence_record(self, org_id: str, record_id: str) -> Optional[EvidenceRecord]:
        """The effective record (original + overrides), as cached in record_state."""
        self._require_org(org_id)
        with self._conn() as c:
            row = c.execute("SELECT payload_json FROM record_state WHERE org_id = ? AND record_id = ?",
                            (org_id, record_id)).fetchone()
        return EvidenceRecord.model_validate_json(row["payload_json"]) if row else None

    def get_original_record(self, org_id: str, record_id: str) -> Optional[EvidenceRecord]:
        self._require_org(org_id)
        with self._conn() as c:
            row = c.execute("SELECT payload_json FROM prep_records WHERE org_id = ? AND record_id = ?",
                            (org_id, record_id)).fetchone()
        return EvidenceRecord.model_validate_json(row["payload_json"]) if row else None

    def list_records(self, org_id: str, limit: int = 50, offset: int = 0,
                     decision: Optional[str] = None) -> List[Dict[str, Any]]:
        self._require_org(org_id)
        q = ("SELECT record_id, unit_id, category, decision, dispatch, status, provider, total_latency_ms,"
             " captured_at, content_hash FROM record_state WHERE org_id = ?")
        args: List[Any] = [org_id]
        if decision:
            q += " AND decision = ?"
            args.append(decision)
        q += " ORDER BY captured_at DESC LIMIT ? OFFSET ?"
        args += [max(1, min(limit, 200)), max(0, offset)]
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def get_overrides(self, org_id: str, record_id: str) -> List[Dict[str, Any]]:
        self._require_org(org_id)
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM overrides WHERE org_id = ? AND record_id = ? ORDER BY seq", (org_id, record_id)).fetchall()]

    def get_seals(self, org_id: str, record_id: str) -> List[Dict[str, Any]]:
        self._require_org(org_id)
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM seals WHERE org_id = ? AND record_id = ? ORDER BY seq", (org_id, record_id)).fetchall()]

    # ------------------------------------------------------------------ overrides (append-only, CAS)
    def record_override(self, org_id: str, record_id: str, entry: OverrideEntry,
                        expected_content_hash: Optional[str] = None) -> EvidenceRecord:
        self._require_org(org_id)
        with self._lock, self._conn(immediate=True) as c:  # BEGIN IMMEDIATE serialises concurrent writers
            row = c.execute("SELECT payload_json, content_hash, version FROM record_state"
                            " WHERE org_id = ? AND record_id = ?", (org_id, record_id)).fetchone()
            if row is None:
                raise TenantAccessDeniedError(f"Record {record_id} not found for tenant {org_id}")
            if expected_content_hash and expected_content_hash != row["content_hash"]:
                raise ConcurrentOverrideError(
                    "Record changed since you loaded it (another override was saved). Reload and try again.")
            current = EvidenceRecord.model_validate_json(row["payload_json"])
            last = c.execute("SELECT mac FROM seals WHERE org_id = ? AND record_id = ? ORDER BY seq DESC LIMIT 1",
                             (org_id, record_id)).fetchone()
            seq = int(row["version"]) + 1
            updated = apply_override(current, entry)
            final_entry = updated.overrides[-1]
            mac = make_mac(org_id, record_id, seq, "override", updated.content_hash, last["mac"] if last else "")
            updated.seal = seal_info(seq, "override", mac)
            c.execute(
                "INSERT INTO overrides (org_id, record_id, seq, entry_json, check_key, original_verdict, new_verdict, reason,"
                " operator_id, role, overridden_at, previous_content_hash, new_content_hash)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (org_id, record_id, seq, final_entry.model_dump_json(), final_entry.check_key,
                 final_entry.original_verdict.value, final_entry.new_verdict.value, final_entry.reason,
                 final_entry.operator_id, final_entry.role, final_entry.overridden_at,
                 final_entry.previous_content_hash, final_entry.new_content_hash))
            c.execute("INSERT INTO seals (org_id, record_id, seq, kind, content_hash, prev_mac, mac, key_id, created_at)"
                      " VALUES (?,?,?,?,?,?,?,?,?)",
                      (org_id, record_id, seq, "override", updated.content_hash, last["mac"] if last else "", mac,
                       updated.seal["key_id"], _now()))
            self._write_state(c, updated, version=seq)
        updated.persisted = True
        return updated

    # ------------------------------------------------------------------ verification
    def verify(self, org_id: str, record_id: str) -> Dict[str, Any]:
        """Replay original + overrides; check every hash and keyed seal, and the cached state."""
        self._require_org(org_id)
        original = self.get_original_record(org_id, record_id)
        if original is None:
            raise TenantAccessDeniedError(f"Record {record_id} not found for tenant {org_id}")
        seals = self.get_seals(org_id, record_id)
        overrides = self.get_overrides(org_id, record_id)
        problems: List[str] = []

        if not seals or seals[0]["seq"] != 0 or seals[0]["kind"] != "original":
            problems.append("original seal missing")
        original_hash_ok = original.verify_integrity()
        if not original_hash_ok:
            problems.append("original record content does not match its stored hash")
        if seals and seals[0]["content_hash"] != original.compute_content_hash():
            problems.append("original record does not match seal 0")

        prev_mac = ""
        for s in seals:
            if not check_mac(org_id, record_id, s["seq"], s["kind"], s["content_hash"], prev_mac, s["mac"]):
                problems.append(f"seal {s['seq']} MAC invalid (not produced with the server seal key)")
            if s["prev_mac"] != prev_mac:
                problems.append(f"seal {s['seq']} not chained to seal {s['seq'] - 1}")
            prev_mac = s["mac"]

        if len(seals) != len(overrides) + 1:
            problems.append(f"{len(overrides)} override(s) but {len(seals)} seal(s)")
        replay = original
        for i, o in enumerate(overrides, start=1):
            entry = OverrideEntry.model_validate_json(o["entry_json"])
            replay = apply_override(replay, entry)
            if i < len(seals) and seals[i]["content_hash"] != replay.content_hash:
                problems.append(f"replaying override {i} does not reproduce seal {i}")

        state = self.get_evidence_record(org_id, record_id)
        state_ok = state is not None and state.compute_content_hash() == replay.content_hash \
            and state.content_hash == replay.content_hash
        if not state_ok:
            problems.append("current record state differs from the replayed seal chain (state was edited)")
        if seals and seals[-1]["content_hash"] != replay.content_hash:
            problems.append("end of seal chain does not match the current record")

        return {
            "record_id": record_id,
            "integrity_verified": not problems,
            "original_hash": seals[0]["content_hash"] if seals else None,
            "current_hash": state.content_hash if state else None,
            "recomputed_hash": replay.content_hash,
            "seal_chain_length": len(seals),
            "override_chain_length": len(overrides),
            "override_chain_linked": not any("chain" in p or "seal" in p for p in problems),
            "key_id": seals[0]["key_id"] if seals else None,
            "problems": problems,
            "method": "Replays the immutable original through every append-only override; checks each SHA-256 "
                      "content hash and each HMAC-SHA256 seal (key held outside the database).",
        }

    # ------------------------------------------------------------------ metrics
    def metrics(self, org_id: str) -> Dict[str, Any]:
        self._require_org(org_id)
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT decision, status, provider, cost_usd, total_latency_ms FROM record_state WHERE org_id = ?",
                (org_id,)).fetchall()]
            checks = [dict(r) for r in c.execute(
                "SELECT check_key, verdict, COUNT(*) AS n FROM check_verdicts WHERE org_id = ? GROUP BY check_key, verdict",
                (org_id,)).fetchall()]
            reasons = [dict(r) for r in c.execute(
                "SELECT reason_code, COUNT(*) AS n FROM check_verdicts WHERE org_id = ? AND verdict IN ('FAIL','UNCERTAIN')"
                " GROUP BY reason_code ORDER BY n DESC LIMIT 8", (org_id,)).fetchall()]
            n_over = c.execute("SELECT COUNT(*) FROM overrides WHERE org_id = ?", (org_id,)).fetchone()[0]
        total = len(rows)
        by_dec = {d.value: sum(1 for r in rows if r["decision"] == d.value) for d in OverallDecisionEnum}
        lat = [r["total_latency_ms"] for r in rows if r["status"] != "failed_open"]
        per_check: Dict[str, Dict[str, int]] = {}
        for r in checks:
            per_check.setdefault(r["check_key"], {})[r["verdict"]] = r["n"]
        providers: Dict[str, int] = {}
        for r in rows:
            providers[r["provider"] or "none"] = providers.get(r["provider"] or "none", 0) + 1
        return {
            "total_units": total,
            "decisions": by_dec,
            "pass_rate": round(by_dec["PASS"] / total, 3) if total else 0.0,
            "uncertain_rate": round((by_dec["UNCERTAIN"] + by_dec["PENDING_REVIEW"]) / total, 3) if total else 0.0,
            "fail_open_count": sum(1 for r in rows if r["status"] == "failed_open"),
            "override_count": n_over,
            "latency_ms": {"p50": _percentile(lat, 50), "p95": _percentile(lat, 95), "max": round(max(lat), 1) if lat else 0.0},
            "avg_cost_usd": round(sum(r["cost_usd"] or 0 for r in rows) / total, 6) if total else 0.0,
            "providers": providers,
            "per_check": per_check,
            "top_reason_codes": reasons,
        }

    # ------------------------------------------------------------------ assets (uploaded photos)
    def save_asset(self, org_id: str, data: bytes, sha256: str, content_type: str, ext: str,
                   original_sha256: Optional[str] = None) -> str:
        self._require_org(org_id)
        asset_id = uuid.uuid4().hex
        folder = self.upload_dir / org_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{asset_id}{ext}"
        path.write_bytes(data)
        with self._conn() as c:
            c.execute("INSERT INTO assets (org_id, asset_id, sha256, original_sha256, storage_path, content_type,"
                      " size_bytes, created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (org_id, asset_id, sha256, original_sha256, str(path), content_type, len(data), _now()))
        return asset_id

    def get_asset(self, org_id: str, asset_id: str) -> Optional[Dict[str, Any]]:
        self._require_org(org_id)
        with self._conn() as c:
            row = c.execute("SELECT * FROM assets WHERE org_id = ? AND asset_id = ?", (org_id, asset_id)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ Round 3 pod idempotency
    def get_pod_output(self, org_id: str, request_id: str) -> Optional[Dict[str, Any]]:
        self._require_org(org_id)
        with self._conn() as c:
            row = c.execute("SELECT output_json FROM pod_requests WHERE org_id = ? AND request_id = ?",
                            (org_id, request_id)).fetchone()
        return json.loads(row["output_json"]) if row else None

    def save_pod_output(self, org_id: str, request_id: str, record_id: str, output: Dict[str, Any]) -> None:
        self._require_org(org_id)
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO pod_requests (org_id, request_id, record_id, output_json, created_at)"
                      " VALUES (?,?,?,?,?)", (org_id, request_id, record_id, json.dumps(output), _now()))

    # ------------------------------------------------------------------ red-team audit
    def cross_tenant_leakage_rows(self, org_a: str, org_b: str) -> int:
        """Count rows of org_a reachable through org_b-scoped queries (must be 0)."""
        leaks = 0
        with self._conn() as c:
            ids = [r[0] for r in c.execute("SELECT record_id FROM prep_records WHERE org_id = ?", (org_a,))]
            assets = [r[0] for r in c.execute("SELECT asset_id FROM assets WHERE org_id = ?", (org_a,))]
        for rid in ids:
            if self.get_evidence_record(org_b, rid) is not None or self.get_original_record(org_b, rid) is not None:
                leaks += 1
            leaks += len(self.get_overrides(org_b, rid)) + len(self.get_seals(org_b, rid))
        for aid in assets:
            if self.get_asset(org_b, aid) is not None:
                leaks += 1
        leaks += sum(1 for r in self.list_records(org_b, limit=200) if r["record_id"] in set(ids))
        return leaks
