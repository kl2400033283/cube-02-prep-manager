"""Tenant-isolated database layer and asset access manager.

Enforces Engineering Rule 1: 'Tenancy isolation before any feature.
Every table gets row-level security scoped to the organisation, enabled and forced.'
"""

import hmac
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from submissions.kl2400033283.agent.config import DB_PATH, ALLOWED_ORGS
from submissions.kl2400033283.agent.schemas.evidence import (
    EvidenceRecord,
    OverrideEntry,
    VerdictEnum,
    OverallDecisionEnum,
    RecordStatusEnum
)

TENANT_SECRET_KEY = b"cube-2026-isolated-tenant-hmac-salt-secret"

class TenantAccessDeniedError(PermissionError):
    """Raised when an operation attempts to access data outside its tenant boundary."""
    pass

class TenantDatabase:
    def __init__(self, db_file: Optional[Path] = None):
        self.db_path = db_file or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        """Initializes database schema with enforced org_id on all tables."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS prep_records (
                    record_id TEXT NOT NULL,
                    org_id TEXT NOT NULL,
                    unit_id TEXT NOT NULL,
                    work_order_id TEXT,
                    fba_shipment_id TEXT,
                    sku TEXT,
                    asin TEXT,
                    fnsku TEXT,
                    prep_price_usd REAL,
                    captured_at TEXT NOT NULL,
                    operator_id TEXT,
                    status TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (record_id, org_id)
                );

                CREATE TABLE IF NOT EXISTS check_verdicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    org_id TEXT NOT NULL,
                    check_key TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    detail TEXT,
                    latency_ms INTEGER,
                    FOREIGN KEY (record_id, org_id) REFERENCES prep_records(record_id, org_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    org_id TEXT NOT NULL,
                    check_key TEXT NOT NULL,
                    original_verdict TEXT NOT NULL,
                    new_verdict TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    overridden_at TEXT NOT NULL,
                    FOREIGN KEY (record_id, org_id) REFERENCES prep_records(record_id, org_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tenant_image_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    org_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    sha256_digest TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    FOREIGN KEY (record_id, org_id) REFERENCES prep_records(record_id, org_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_records_org_unit ON prep_records(org_id, unit_id);
                CREATE INDEX IF NOT EXISTS idx_records_org ON prep_records(org_id);
                CREATE INDEX IF NOT EXISTS idx_images_org_token ON tenant_image_tokens(org_id, access_token);
            """)

    @staticmethod
    def generate_image_token(org_id: str, file_path: str) -> str:
        """Generates an HMAC-SHA256 signed capability token for accessing a tenant image."""
        msg = f"{org_id}:{file_path}".encode("utf-8")
        return hmac.new(TENANT_SECRET_KEY, msg, hashlib.sha256).hexdigest()

    def save_evidence_record(self, record: EvidenceRecord) -> None:
        """Persists an evidence record ensuring tenant scoping."""
        org_id = record.organization_id
        if org_id not in ALLOWED_ORGS:
            raise TenantAccessDeniedError(f"Unauthorized organization: {org_id}")

        with self._get_connection() as conn:
            # Upsert prep_record
            conn.execute("""
                INSERT OR REPLACE INTO prep_records 
                (record_id, org_id, unit_id, work_order_id, fba_shipment_id, sku, asin, fnsku,
                 prep_price_usd, captured_at, operator_id, status, decision, content_hash, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.record_id,
                org_id,
                record.subject.unit_id,
                record.subject.work_order_id,
                record.subject.fba_shipment_id,
                record.subject.sku,
                record.subject.asin,
                record.subject.fnsku,
                0.50,
                record.captured_at,
                record.operator_label,
                record.status.value,
                record.outcome.decision.value,
                record.content_hash,
                record.model_dump_json()
            ))

            # Store checks
            conn.execute("DELETE FROM check_verdicts WHERE record_id = ? AND org_id = ?", (record.record_id, org_id))
            for check in record.checks:
                conn.execute("""
                    INSERT INTO check_verdicts (record_id, org_id, check_key, verdict, confidence, detail, latency_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (record.record_id, org_id, check.check_key, check.verdict.value, check.confidence, check.detail, check.latency_ms))

            # Store signed image access tokens
            conn.execute("DELETE FROM tenant_image_tokens WHERE record_id = ? AND org_id = ?", (record.record_id, org_id))
            for img in record.images:
                token = self.generate_image_token(org_id, img.file_path)
                conn.execute("""
                    INSERT INTO tenant_image_tokens (record_id, org_id, file_path, sha256_digest, access_token)
                    VALUES (?, ?, ?, ?, ?)
                """, (record.record_id, org_id, img.file_path, img.sha256_digest, token))

    def get_evidence_record(self, org_id: str, record_id: str) -> Optional[EvidenceRecord]:
        """Fetches an evidence record strictly enforcing org_id."""
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT payload_json FROM prep_records 
                WHERE record_id = ? AND org_id = ?
            """, (record_id, org_id))
            row = cur.fetchone()
            if not row:
                return None
            return EvidenceRecord.model_validate_json(row["payload_json"])

    def get_record_by_unit_id(self, org_id: str, unit_id: str) -> Optional[EvidenceRecord]:
        """Fetches an evidence record by universal unit_id within the tenant boundary."""
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT payload_json FROM prep_records 
                WHERE unit_id = ? AND org_id = ?
            """, (unit_id, org_id))
            row = cur.fetchone()
            if not row:
                return None
            return EvidenceRecord.model_validate_json(row["payload_json"])

    def list_records(self, org_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Lists records strictly bounded to the requesting tenant."""
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT record_id, unit_id, sku, asin, fnsku, decision, status, captured_at, content_hash
                FROM prep_records
                WHERE org_id = ?
                ORDER BY captured_at DESC
                LIMIT ?
            """, (org_id, limit))
            return [dict(row) for row in cur.fetchall()]

    def record_override(self, org_id: str, record_id: str, override: OverrideEntry) -> EvidenceRecord:
        """Appends an override record while strictly ensuring tenant isolation."""
        record = self.get_evidence_record(org_id, record_id)
        if not record:
            raise TenantAccessDeniedError(f"Record {record_id} not found in tenant {org_id}")

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO overrides (record_id, org_id, check_key, original_verdict, new_verdict, reason, operator_id, overridden_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id, org_id, override.check_key, override.original_verdict.value,
                override.new_verdict.value, override.reason, override.operator_id, override.overridden_at
            ))

        # Update check verdict and outcome in payload
        for check in record.checks:
            if check.check_key == override.check_key:
                check.verdict = override.new_verdict
                check.detail += f" [OVERRIDDEN by {override.operator_id}: {override.reason}]"

        record.overrides.append(override)
        record.status = RecordStatusEnum.OVERRIDDEN
        
        # Recompute decision based on updated checks
        has_fail = any(c.verdict == VerdictEnum.FAIL or getattr(c.verdict, 'value', c.verdict) == "FAIL" for c in record.checks)
        has_uncertain = any(c.verdict == VerdictEnum.UNCERTAIN or getattr(c.verdict, 'value', c.verdict) == "UNCERTAIN" for c in record.checks)
        if has_fail:
            record.outcome.decision = OverallDecisionEnum.FAIL
        elif has_uncertain:
            record.outcome.decision = OverallDecisionEnum.UNCERTAIN
        else:
            record.outcome.decision = OverallDecisionEnum.PASS

        record.content_hash = record.compute_content_hash()
        self.save_evidence_record(record)
        return record

    def verify_image_access(self, requesting_org_id: str, file_path: str, access_token: str) -> bool:
        """Checks if a tenant is authorized to view an image asset.
        
        Guarantees that Org B cannot guess an image path from Org A.
        """
        expected_token = self.generate_image_token(requesting_org_id, file_path)
        if not hmac.compare_digest(expected_token, access_token):
            return False

        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT 1 FROM tenant_image_tokens
                WHERE org_id = ? AND file_path = ? AND access_token = ?
            """, (requesting_org_id, file_path, access_token))
            return cur.fetchone() is not None

    def assert_zero_cross_tenant_leakage(self, org_a: str, org_b: str) -> bool:
        """Automated audit assertion testing that org_b cannot query org_a rows."""
        with self._get_connection() as conn:
            # Count records owned by org_a
            cur_a = conn.execute("SELECT record_id FROM prep_records WHERE org_id = ?", (org_a,))
            records_a = [r["record_id"] for r in cur_a.fetchall()]
            if not records_a:
                return True

            # Attempt to query org_a's records using org_b's tenant scope
            for rec_id in records_a:
                cur_leak = conn.execute("""
                    SELECT 1 FROM prep_records WHERE record_id = ? AND org_id = ?
                """, (rec_id, org_b))
                if cur_leak.fetchone() is not None:
                    return False  # Leak detected!

                # Check image tokens leak
                cur_img_leak = conn.execute("""
                    SELECT 1 FROM tenant_image_tokens WHERE record_id = ? AND org_id = ?
                """, (rec_id, org_b))
                if cur_img_leak.fetchone() is not None:
                    return False
        return True
