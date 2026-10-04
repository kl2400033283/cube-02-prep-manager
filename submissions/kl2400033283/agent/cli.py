"""Headless Command Line Interface for Prep Manager (Agent 02).

Usage:
  python -m submissions.kl2400033283.agent.cli check --unit-id UNIT-0004 --org-id org_demo_alpha
  python -m submissions.kl2400033283.agent.cli batch --csv-path data/prep_sample.csv --org-id org_demo_alpha
  python -m submissions.kl2400033283.agent.cli verify-hash --record-id PRP-0004 --org-id org_demo_alpha
  python -m submissions.kl2400033283.agent.cli override --record-id PRP-0004 --org-id org_demo_alpha --check-key original_barcode_covered --verdict PASS --reason "MANUAL_SCAN_OK"
  python -m submissions.kl2400033283.agent.cli test-isolation
"""

import sys
import json
import csv
import argparse
from pathlib import Path

from submissions.kl2400033283.agent.schemas.evidence import PrepInspectionInput
from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent
from submissions.kl2400033283.agent.db.database import TenantDatabase

def cmd_check(args):
    agent = PrepManagerAgent()
    input_data = PrepInspectionInput(
        unit_id=args.unit_id,
        org_id=args.org_id,
        work_order_id=args.work_order_id,
        fba_shipment_id=args.fba_shipment_id,
        sku=args.sku,
        asin=args.asin,
        fnsku=args.fnsku,
        wo_polybag=args.wo_polybag,
        wo_suffocation_warning=args.wo_suffocation_warning,
        wo_expiry_date=args.wo_expiry_date,
        wo_handling_marks=args.wo_handling_marks,
        operator_id=args.operator_id,
        test_mode_features={
            "polybag_present_sealed": args.polybag_state,
            "suffocation_warning": args.warning_state,
            "fnsku_label_placement": args.fnsku_placement,
            "original_barcode_covered": args.barcode_covered,
            "expiry_date": args.expiry_state,
            "handling_marks": args.handling_state
        }
    )
    record = agent.process_unit(input_data)
    
    print("\n=======================================================")
    print(f"PREP MANAGER INSPECTION RESULT: {record.record_id} ({record.subject.unit_id})")
    print("=======================================================")
    print(f"Tenant:         {record.organization_id}")
    print(f"Overall Status: {record.outcome.decision.value}")
    print(f"Summary:        {record.outcome.summary}")
    print(f"Content Hash:   {record.content_hash}")
    print(f"Integrity Proof:{'VALID (VERIFIED)' if record.verify_integrity() else 'CORRUPTED'}")
    print("-------------------------------------------------------")
    print("CHECKS BREAKDOWN:")
    for c in record.checks:
        symbol = "[PASS]" if c.verdict.value == "PASS" else ("[FAIL]" if c.verdict.value == "FAIL" else ("[UNCERTAIN]" if c.verdict.value == "UNCERTAIN" else "[N/A]"))
        print(f"  {symbol:<13} {c.check_key:<26} (conf: {c.confidence:.2f}) - {c.detail}")
    print("=======================================================\n")

def cmd_batch(args):
    csv_file = Path(args.csv_path)
    if not csv_file.exists():
        print(f"Error: CSV file not found: {csv_file}")
        sys.exit(1)

    agent = PrepManagerAgent()
    passed = 0
    failed = 0
    uncertain = 0
    total = 0

    print(f"\nProcessing batch from {csv_file.name} for tenant {args.org_id}...")
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("org_id") != args.org_id:
                continue
            total += 1
            input_data = PrepInspectionInput(
                unit_id=row["unit_id"],
                org_id=row["org_id"],
                work_order_id=row.get("work_order_id", "WO-3000"),
                fba_shipment_id=row.get("fba_shipment_id", "FBA-100"),
                sku=row.get("sku", "SKU-TEST"),
                asin=row.get("asin", "B0TEST"),
                fnsku=row.get("fnsku", "X00TEST"),
                wo_polybag=row.get("wo_polybag", "False").lower() == "true",
                wo_suffocation_warning=row.get("wo_suffocation_warning", "False").lower() == "true",
                wo_expiry_date=row.get("wo_expiry_date", "False").lower() == "true",
                wo_handling_marks=row.get("wo_handling_marks") or None,
                operator_id=row.get("operator_id", "op_cli"),
                test_mode_features={
                    "polybag_present_sealed": row.get("polybag_present_sealed", "yes"),
                    "suffocation_warning": row.get("suffocation_warning", "legible"),
                    "fnsku_label_placement": row.get("fnsku_label_placement", "flat"),
                    "original_barcode_covered": row.get("original_barcode_covered", "yes"),
                    "expiry_date": row.get("expiry_date", "legible"),
                    "handling_marks": row.get("handling_marks", "all_present")
                }
            )
            rec = agent.process_unit(input_data)
            dec = rec.outcome.decision.value
            if dec == "PASS":
                passed += 1
            elif dec == "FAIL":
                failed += 1
            else:
                uncertain += 1
            print(f"  Processed {rec.subject.unit_id} ({rec.record_id}) -> {dec}")

    print("\nBatch Summary:")
    print(f"  Total Processed: {total}")
    print(f"  Passed:          {passed} ({passed/max(total,1)*100:.1f}%)")
    print(f"  Failed:          {failed} ({failed/max(total,1)*100:.1f}%)")
    print(f"  Uncertain:       {uncertain} ({uncertain/max(total,1)*100:.1f}%)\n")

def cmd_override(args):
    agent = PrepManagerAgent()
    try:
        updated = agent.apply_override(
            org_id=args.org_id,
            record_id=args.record_id,
            check_key=args.check_key,
            new_verdict_str=args.verdict,
            reason=args.reason,
            operator_id=args.operator_id
        )
        print(f"\nSuccessfully applied override to {updated.record_id} for check {args.check_key} -> {args.verdict}")
        print(f"New Overall Decision: {updated.outcome.decision.value}")
        print(f"New Content Hash:     {updated.content_hash}")
        print(f"Audit log overrides:  {len(updated.overrides)} recorded.\n")
    except Exception as e:
        print(f"Error applying override: {e}")
        sys.exit(1)

def cmd_verify_hash(args):
    db = TenantDatabase()
    record = db.get_evidence_record(args.org_id, args.record_id)
    if not record:
        print(f"Error: Record {args.record_id} not found in tenant {args.org_id}")
        sys.exit(1)

    is_valid = record.verify_integrity()
    print("\n=======================================================")
    print(f"CRYPTOGRAPHIC EVIDENCE RECORD INTEGRITY: {record.record_id}")
    print("=======================================================")
    print(f"Tenant:         {record.organization_id}")
    print(f"Unit ID:        {record.subject.unit_id}")
    print(f"Stored Hash:    {record.content_hash}")
    print(f"Calculated Hash:{record.compute_content_hash()}")
    print(f"Status:         {'VALID (VERIFIED PROOF)' if is_valid else 'TAMPERED / MISMATCH'}")
    print("=======================================================\n")

def cmd_test_isolation(args):
    db = TenantDatabase()
    print("\nRunning Automated Tenant Isolation Red-Team Test...")
    is_safe = db.assert_zero_cross_tenant_leakage("org_demo_alpha", "org_demo_bravo")
    if is_safe:
        print("PASS: Zero cross-tenant data leakage verified between org_demo_alpha and org_demo_bravo.")
    else:
        print("FAIL: Cross-tenant data leakage detected!")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Prep Manager Headless CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Check
    p_check = subparsers.add_parser("check", help="Inspect a single product unit")
    p_check.add_argument("--unit-id", required=True, help="Universal unit id (e.g. UNIT-0004)")
    p_check.add_argument("--org-id", default="org_demo_alpha", help="Tenant ID")
    p_check.add_argument("--sku", default="SKU-PROT-1KG")
    p_check.add_argument("--asin", default="B0DUMMY357")
    p_check.add_argument("--fnsku", default="X00DUMMY004")
    p_check.add_argument("--work-order-id", default="WO-3000")
    p_check.add_argument("--fba-shipment-id", default="FBA-100")
    p_check.add_argument("--operator-id", default="op_cli")
    p_check.add_argument("--wo-polybag", action="store_true", default=False)
    p_check.add_argument("--wo-suffocation-warning", action="store_true", default=False)
    p_check.add_argument("--wo-expiry-date", action="store_true", default=False)
    p_check.add_argument("--wo-handling-marks", default=None)
    p_check.add_argument("--polybag-state", default="yes")
    p_check.add_argument("--warning-state", default="legible")
    p_check.add_argument("--fnsku-placement", default="flat")
    p_check.add_argument("--barcode-covered", default="yes")
    p_check.add_argument("--expiry-state", default="legible")
    p_check.add_argument("--handling-state", default="all_present")

    # Batch
    p_batch = subparsers.add_parser("batch", help="Batch inspect units from CSV")
    p_batch.add_argument("--csv-path", default="data/prep_sample.csv")
    p_batch.add_argument("--org-id", default="org_demo_alpha")

    # Override
    p_over = subparsers.add_parser("override", help="Record operator override")
    p_over.add_argument("--record-id", required=True)
    p_over.add_argument("--org-id", default="org_demo_alpha")
    p_over.add_argument("--check-key", required=True)
    p_over.add_argument("--verdict", required=True)
    p_over.add_argument("--reason", required=True)
    p_over.add_argument("--operator-id", default="op_manual")

    # Verify Hash
    p_hash = subparsers.add_parser("verify-hash", help="Cryptographically verify content hash")
    p_hash.add_argument("--record-id", required=True)
    p_hash.add_argument("--org-id", default="org_demo_alpha")

    # Test Isolation
    p_iso = subparsers.add_parser("test-isolation", help="Run automated tenant boundary check")

    args = parser.parse_args()
    if args.command == "check":
        cmd_check(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "override":
        cmd_override(args)
    elif args.command == "verify-hash":
        cmd_verify_hash(args)
    elif args.command == "test-isolation":
        cmd_test_isolation(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
