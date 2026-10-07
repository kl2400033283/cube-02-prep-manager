"""Headless CLI for Prep Manager.

  python -m submissions.kl2400033283.agent.cli scenarios
  python -m submissions.kl2400033283.agent.cli inspect --scenario fnsku-on-seam
  python -m submissions.kl2400033283.agent.cli inspect --image photo.jpg --unit-id UNIT-9 --category plush_toy --wo-polybag
  python -m submissions.kl2400033283.agent.cli verify --record-id PRP-S05-1a2b3c4d
  python -m submissions.kl2400033283.agent.cli override --record-id ... --check fnsku_label_placement --verdict PASS --reason "relabelled"
  python -m submissions.kl2400033283.agent.cli audit
"""

import argparse
import json
import sys

from submissions.kl2400033283.agent.config import ALLOWED_ORGS
from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent
from submissions.kl2400033283.agent.schemas.evidence import PrepInspectionInput
from submissions.kl2400033283.agent.sim.scenarios import BY_ID, SCENARIOS

SYM = {"PASS": "PASS ", "FAIL": "FAIL ", "UNCERTAIN": "UNCRT", "NOT_REQUIRED": " n/a ", "PENDING_REVIEW": "PEND "}


def print_record(rec):
    print(f"\n{rec.record_id}  unit={rec.subject.unit_id}  tenant={rec.organization_id}")
    print(f"PREP STATUS: {rec.outcome.decision.value}  ->  {rec.outcome.dispatch.value}")
    print(f"  {rec.outcome.summary}")
    for c in rec.checks:
        print(f"  [{SYM[c.verdict.value]}] {c.title:<28} conf={c.confidence:.2f}  {c.reason_code:<26} {c.detail[:90]}")
    for d in rec.discrepancies:
        print(f"  ! {d['code']}: {d['detail']}")
    for a in rec.outcome.action_items:
        print(f"  -> {a}")
    p = rec.perception
    print(f"  perception={p.provider if p else '-'} calls={p.model_calls if p else 0} latency={rec.total_latency_ms:.0f}ms")
    print(f"  sha256={rec.content_hash}  verified={rec.verify_integrity()}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="prep-manager")
    ap.add_argument("--org", default="org_demo_alpha", choices=ALLOWED_ORGS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scenarios")
    i = sub.add_parser("inspect")
    i.add_argument("--scenario", choices=list(BY_ID))
    i.add_argument("--image", action="append", default=[])
    i.add_argument("--unit-id", default="UNIT-CLI")
    i.add_argument("--category", default="general")
    i.add_argument("--wo-polybag", action="store_true")
    i.add_argument("--wo-warning", action="store_true")
    i.add_argument("--wo-expiry", action="store_true")
    i.add_argument("--mark", action="append", default=[])
    i.add_argument("--bag", nargs=3, type=float, metavar=("L", "W", "OPENING"))
    i.add_argument("--calibrated", action="store_true", help="frames are from the calibrated station")
    i.add_argument("--json", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--record-id", required=True)
    o = sub.add_parser("override")
    o.add_argument("--record-id", required=True)
    o.add_argument("--check", required=True)
    o.add_argument("--verdict", required=True, choices=["PASS", "FAIL", "UNCERTAIN"])
    o.add_argument("--reason", required=True)
    o.add_argument("--operator", default="op_cli")
    sub.add_parser("audit")
    args = ap.parse_args(argv)
    agent = PrepManagerAgent()

    if args.cmd == "scenarios":
        for s in SCENARIOS:
            print(f"{s.scenario_id:<24} expected={s.expected:<10} {s.challenge_case}")
    elif args.cmd == "inspect":
        if args.scenario:
            s = BY_ID[args.scenario]
            inp = PrepInspectionInput(org_id=args.org, image_paths=[str(s.ensure_rendered())],
                                      image_asset_ids=[f"scenario:{s.scenario_id}"], station_calibrated=True, **s.unit)
        else:
            if not args.image:
                sys.exit("give --scenario or at least one --image")
            bag = dict(zip(("bag_length_in", "bag_width_in", "bag_opening_in"), args.bag or (None, None, None)))
            inp = PrepInspectionInput(org_id=args.org, unit_id=args.unit_id, category=args.category,
                                      wo_polybag=args.wo_polybag, wo_suffocation_warning=args.wo_warning,
                                      wo_expiry_date=args.wo_expiry, wo_handling_marks=args.mark,
                                      image_paths=args.image, station_calibrated=args.calibrated, **bag)
        rec = agent.inspect(inp)
        print(rec.model_dump_json(indent=2) if args.json else "", end="")
        if not args.json:
            print_record(rec)
    elif args.cmd == "verify":
        rec = agent.db.get_evidence_record(args.org, args.record_id)
        if not rec:
            sys.exit("record not found in this tenant")
        print(json.dumps({"record_id": rec.record_id, "verified": rec.verify_integrity(),
                          "stored": rec.content_hash, "recomputed": rec.compute_content_hash()}, indent=2))
    elif args.cmd == "override":
        print_record(agent.apply_override(args.org, args.record_id, args.check, args.verdict, args.reason, args.operator))
    elif args.cmd == "audit":
        a, b = ALLOWED_ORGS
        n = agent.db.cross_tenant_leakage_rows(a, b) + agent.db.cross_tenant_leakage_rows(b, a)
        print(f"cross-tenant rows visible: {n}  ->  {'ISOLATED' if n == 0 else 'LEAK'}")


if __name__ == "__main__":
    main()
