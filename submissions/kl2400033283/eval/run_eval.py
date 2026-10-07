"""Evaluation harness for Prep Manager.

    python submissions/kl2400033283/eval/run_eval.py

1. Generates the 50-unit held-out set (eval/dataset_generator.py).
2. Runs the full agent (same code path as the API) on the *images only*.
   Ground truth never reaches the agent.
3. Scores per check and per unit. Positive class = defect (FAIL):
     FN = truth FAIL, agent PASS   (a defect shipped - the costly error)
     FP = truth PASS, agent FAIL   (needless rework)
     UNCERTAIN = abstention, reported separately (coverage)
4. Human agreement: if eval/labels/annotator_a.csv and annotator_b.csv are
   filled in (unit_id, overall), Cohen's kappa between them and agent-vs-
   consensus agreement are reported. Otherwise the report says plainly that
   human labels are pending - nothing is simulated.
5. Writes eval/eval_results.json (served to the UI) and eval-report.md.
"""

import csv
import json
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.config import (
    AGENT_VERSION, CV_ENGINE_VERSION, EVAL_RESULTS_PATH, KC1_MAX_BARCODE_FN_RATE, RULES_VERSION, SUBMISSION_DIR,
)
from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent
from submissions.kl2400033283.agent.db.database import TenantDatabase
from submissions.kl2400033283.agent.rules.authoritative_rules import CHECK_KEYS, CHECK_TITLES
from submissions.kl2400033283.agent.schemas.evidence import PrepInspectionInput
from submissions.kl2400033283.eval.dataset_generator import generate

LABEL_DIR = SUBMISSION_DIR / "eval" / "labels"
REPORT_PATH = SUBMISSION_DIR / "eval-report.md"


def cohen_kappa(a, b):
    labels = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[l] * cb[l] for l in labels) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def load_human_labels(items):
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for who in ("a", "b"):
        path = LABEL_DIR / f"annotator_{who}.csv"
        if not path.exists():
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["unit_id", "image", "overall", "notes"])
                for it in items:
                    w.writerow([it["unit"]["unit_id"], it["image"], "", ""])
        with open(path, newline="", encoding="utf-8") as f:
            rows = {r["unit_id"]: r["overall"].strip().upper() for r in csv.DictReader(f)}
        out[who] = rows
    complete = all(len([v for v in out[w].values() if v in ("PASS", "FAIL", "UNCERTAIN")]) == len(items) for w in out)
    return out if complete else None


def main():
    print("Generating held-out set ...")
    items = generate()
    tmp = Path(tempfile.mkdtemp())
    agent = PrepManagerAgent(db=TenantDatabase(tmp / "eval.db", tmp / "uploads"), mode="cv")

    per_check = {k: Counter() for k in CHECK_KEYS}
    rows, latencies, costs = [], [], []
    by_condition = defaultdict(Counter)
    print("Running agent on 50 units (pixels only) ...")
    for it in items:
        u = it["unit"]
        inp = PrepInspectionInput(org_id="org_demo_alpha", image_paths=[str(SUBMISSION_DIR / it["image"])],
                                  station_calibrated=True, **u)
        t = time.perf_counter()
        rec = agent.inspect(inp)
        latencies.append((time.perf_counter() - t) * 1000)
        costs.append(rec.perception.cost_usd if rec.perception else 0.0)
        truth = it["truth"]
        notes = []
        for c in rec.checks:
            tv, av = truth[c.check_key], c.verdict.value
            if tv == "NOT_REQUIRED":
                per_check[c.check_key]["not_required_ok" if av == "NOT_REQUIRED" else "requirement_mismatch"] += 1
                continue
            if av == "UNCERTAIN":
                per_check[c.check_key]["uncertain"] += 1
                notes.append(f"{c.check_key}: UNCERTAIN ({c.reason_code})")
            elif tv == "FAIL" and av == "FAIL":
                per_check[c.check_key]["tp"] += 1
            elif tv == "PASS" and av == "PASS":
                per_check[c.check_key]["tn"] += 1
            elif tv == "FAIL" and av == "PASS":
                per_check[c.check_key]["fn"] += 1
                notes.append(f"{c.check_key}: MISSED DEFECT")
            elif tv == "PASS" and av == "FAIL":
                per_check[c.check_key]["fp"] += 1
                notes.append(f"{c.check_key}: FALSE ALARM ({c.reason_code})")
            else:
                per_check[c.check_key]["requirement_mismatch"] += 1
        agent_overall = rec.outcome.decision.value
        tov = truth["overall"]
        outcome = ("correct" if agent_overall == tov else
                   "abstained" if agent_overall in ("UNCERTAIN", "PENDING_REVIEW") else
                   "missed_defect" if tov == "FAIL" else "false_alarm")
        by_condition[it["optics"]][outcome] += 1
        rows.append({"unit_id": u["unit_id"], "image": it["image"], "condition": it["optics"], "defect": it["defect"],
                     "truth": tov, "agent": agent_overall, "outcome": outcome,
                     "latency_ms": round(latencies[-1], 1), "notes": "; ".join(notes)})

    humans = load_human_labels(items)
    human = None
    if humans:
        ids = [it["unit"]["unit_id"] for it in items]
        a = [humans["a"][i] for i in ids]
        b = [humans["b"][i] for i in ids]
        consensus = [x if x == y else "UNCERTAIN" for x, y in zip(a, b)]
        agent_dec = [r["agent"] if r["agent"] != "PENDING_REVIEW" else "UNCERTAIN" for r in rows]
        human = {"kappa_a_vs_b": round(cohen_kappa(a, b), 4),
                 "agent_vs_consensus_agreement": round(sum(x == y for x, y in zip(agent_dec, consensus)) / len(ids), 4),
                 "kappa_agent_vs_consensus": round(cohen_kappa(agent_dec, consensus), 4)}

    checks_out = {}
    for k, c in per_check.items():
        decided = c["tp"] + c["tn"] + c["fp"] + c["fn"]
        applicable = decided + c["uncertain"]
        checks_out[k] = {
            "title": CHECK_TITLES[k], "applicable": applicable, **{x: c[x] for x in ("tp", "tn", "fp", "fn", "uncertain")},
            "accuracy_on_decided": round((c["tp"] + c["tn"]) / decided, 4) if decided else None,
            "fn_rate": round(c["fn"] / (c["tp"] + c["fn"] + 1e-9), 4) if (c["tp"] + c["fn"]) else 0.0,
            "fp_rate": round(c["fp"] / (c["tn"] + c["fp"] + 1e-9), 4) if (c["tn"] + c["fp"]) else 0.0,
            "uncertain_rate": round(c["uncertain"] / applicable, 4) if applicable else 0.0,
            "requirement_mismatch": c["requirement_mismatch"],
        }
    outcomes = Counter(r["outcome"] for r in rows)
    clean = [r for r in rows if r["condition"] in ("normal", "soft")]
    degraded = [r for r in rows if r["condition"] not in ("normal", "soft")]
    lat_sorted = sorted(latencies)
    barcode = checks_out["original_barcode_covered"]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_version": AGENT_VERSION, "perception": CV_ENGINE_VERSION, "rules_version": RULES_VERSION,
        "units": len(rows), "label_source": "scene-spec ground truth (what was physically rendered)",
        "human_annotation": human or "pending - fill eval/labels/annotator_a.csv and annotator_b.csv, then re-run",
        "overall": dict(outcomes),
        "unit_accuracy": round(outcomes["correct"] / len(rows), 4),
        "clean_accuracy": round(sum(r["outcome"] == "correct" for r in clean) / len(clean), 4),
        "degraded_safe_rate": round(sum(r["outcome"] in ("correct", "abstained") for r in degraded) / len(degraded), 4),
        "missed_defects": outcomes["missed_defect"], "false_alarms": outcomes["false_alarm"],
        "uncertain_rate": round(outcomes["abstained"] / len(rows), 4),
        "by_condition": {k: dict(v) for k, v in by_condition.items()},
        "latency_ms": {"p50": round(statistics.median(latencies), 1),
                       "p95": round(lat_sorted[int(0.95 * (len(lat_sorted) - 1))], 1),
                       "max": round(max(latencies), 1)},
        "cost_per_unit_usd": round(sum(costs) / len(costs), 6),
        "kill_conditions": {"KC1_barcode_fn_rate": barcode["fn_rate"],
                            "KC1_pass": barcode["fn_rate"] <= KC1_MAX_BARCODE_FN_RATE},
        "per_check": checks_out, "units_table": rows,
    }
    EVAL_RESULTS_PATH.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    write_report(summary)
    print(json.dumps({k: summary[k] for k in ("unit_accuracy", "clean_accuracy", "degraded_safe_rate", "missed_defects",
                                              "false_alarms", "uncertain_rate", "latency_ms", "overall")}, indent=1))


def _pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def write_report(s):
    L = []
    L.append("# Prep Manager - Evaluation Report\n")
    L.append(f"_Generated {s['generated_at']} by `eval/run_eval.py` - agent {s['agent_version']}, perception "
             f"`{s['perception']}`, rules `{s['rules_version']}`._\n")
    L.append("## Method\n")
    L.append("- **Held-out set:** 50 units rendered from seeds 50000+. Detector thresholds were tuned only on seeds "
             "1000-9999 and the 13 demo scenarios. The agent receives the JPEG and the work order - nothing else.")
    L.append("- **Conditions:** 34 normal, 6 slight defocus, 4 specular glare, 3 heavy motion blur, 3 under-exposed.")
    L.append("- **Ground truth:** the physical scene that was rendered (e.g. 'UPC 35% exposed'). Positive class = defect.")
    L.append("- **Scoring:** FN = defect passed (shipped), FP = compliant unit failed (rework), UNCERTAIN = abstention "
             "routed to a human. On degraded frames, *safe* = correct or UNCERTAIN.")
    L.append("- **Synthetic data caveat:** renders share one visual vocabulary with the station CV engine. These numbers "
             "show the pipeline works end to end and handles uncertainty; they are **not** a claim about real "
             "warehouse photos. The test set is built by the same renderer the detectors were tuned on, so this "
             "evaluation is partly circular (repo review, 6 Oct 2026). Real photos run through the free vision / "
             "OCR providers, whose accuracy has **not** been measured: that needs a labelled real-photo set.\n")
    L.append("## Headline\n")
    L.append("| Metric | Value |\n|---|---|")
    L.append(f"| Unit decisions correct (all 50) | {_pct(s['unit_accuracy'])} |")
    L.append(f"| Correct on clean + slight-defocus frames | {_pct(s['clean_accuracy'])} |")
    L.append(f"| Safe on degraded frames (correct or UNCERTAIN) | {_pct(s['degraded_safe_rate'])} |")
    L.append(f"| Missed defects (FN units) | {s['missed_defects']} |")
    L.append(f"| False alarms (FP units) | {s['false_alarms']} |")
    L.append(f"| UNCERTAIN rate | {_pct(s['uncertain_rate'])} |")
    L.append(f"| Latency p50 / p95 | {s['latency_ms']['p50']} ms / {s['latency_ms']['p95']} ms |")
    L.append(f"| Model cost per unit | ${s['cost_per_unit_usd']:.4f} (station CV, no model call) |")
    L.append(f"| KC-1 barcode FN rate (limit 1.5%) | {_pct(s['kill_conditions']['KC1_barcode_fn_rate'])} |\n")
    L.append("## Human agreement\n")
    if isinstance(s["human_annotation"], dict):
        h = s["human_annotation"]
        L.append(f"- Annotator A vs B Cohen's kappa: **{h['kappa_a_vs_b']}**")
        L.append(f"- Agent vs human consensus agreement: **{_pct(h['agent_vs_consensus_agreement'])}** "
                 f"(kappa {h['kappa_agent_vs_consensus']})\n")
    else:
        L.append("**Pending.** Two people should label `eval/labels/annotator_a.csv` and `annotator_b.csv` "
                 "independently (column `overall` = PASS / FAIL / UNCERTAIN) before looking at agent output; re-running "
                 "this script then reports their kappa and agent-vs-consensus agreement. Earlier versions of this "
                 "report used simulated annotators; that has been removed.\n")
    L.append("## Per check\n")
    L.append("| Check | Applicable | TP | TN | FP | FN | UNCERTAIN | Acc. on decided | FN rate | FP rate |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for k, c in s["per_check"].items():
        L.append(f"| {c['title']} | {c['applicable']} | {c['tp']} | {c['tn']} | {c['fp']} | {c['fn']} | {c['uncertain']} | "
                 f"{_pct(c['accuracy_on_decided'])} | {_pct(c['fn_rate'])} | {_pct(c['fp_rate'])} |")
    L.append("\n## By capture condition\n")
    L.append("| Condition | correct | abstained | missed_defect | false_alarm |\n|---|---|---|---|---|")
    for cond, c in sorted(s["by_condition"].items()):
        L.append(f"| {cond} | {c.get('correct', 0)} | {c.get('abstained', 0)} | {c.get('missed_defect', 0)} | {c.get('false_alarm', 0)} |")
    L.append("\n## Unit table\n")
    L.append("| Unit | Condition | Built defect | Truth | Agent | Outcome | Notes |\n|---|---|---|---|---|---|---|")
    for r in s["units_table"]:
        L.append(f"| {r['unit_id']} | {r['condition']} | {r['defect']} | {r['truth']} | {r['agent']} | {r['outcome']} | {r['notes']} |")
    L.append("\n## Revision history (read this)\n")
    L.append("- **Run 1 (v2.0.0-rc1):** 40/50 correct, **2 false alarms**, 0 missed defects, 8 abstentions. Both false "
             "alarms were *slight-defocus* frames: blur merged the text lines under the FNSKU bars, so the label was "
             "read as a retail UPC (FNSKU_MISSING + ORIGINAL_BARCODE_EXPOSED).")
    L.append("- **Fix:** reproduced on calibration seeds 8000-8039 (slight defocus), where 57/200 observations were wrong. "
             "Detectors were made defocus-tolerant (FNSKU identified by label body below the bars, seal found by band "
             "brightness instead of 2-px stripe texture, warning-panel strips re-joined, contrast-relative print "
             "detection, thin-keyline test). Calibration regression afterwards: 1000/1000 observations correct across "
             "5 seed batches covering all optics.")
    L.append("- **Run 2:** 42/50 correct (84%), 0 FN, 0 FP, 8 abstentions. Caveat: the held-out set has now been seen "
             "once, so it is no longer strictly blind. Generate a fresh one by changing `SEED_BASE` in "
             "eval/dataset_generator.py.")
    L.append("- **Run 3 (this report, after the repo review fixes):** EVAL-003 (glass, labelled PASS) is now UNCERTAIN "
             "on purpose: the new rule FBA-GL-01 says protective prep for glass cannot be proven from a photo, so it "
             "needs a document/attestation. The label was not changed. Multi-view fusion, native-resolution blur "
             "check, AMBER on work-order gaps and blind FNSKU reads were added; no other unit changed.")
    L.append("\n## Failure modes and limits (honest list)\n")
    L.append("- **Heavy blur / under-exposure:** the quality gate rejects the frame, the model call is skipped and every "
             "check is UNCERTAIN with a recapture instruction. Correct behaviour, but it costs throughput.")
    L.append("- **Glare:** absence-of-defect claims (barcode covered, label flat) near clipped pixels become UNCERTAIN. "
             "Positive defects seen elsewhere in the frame are still reported.")
    L.append("- **Single view:** seals, warnings or dates on the hidden face cannot be seen. Station protocol requires "
             "labels on the camera face; multi-view capture is supported (up to 4 images) and fused conservatively.")
    L.append("- **Not visually measurable:** film thickness (1.5 mil) and master-carton date marking are tracked as "
             "attestations, never as visual verdicts.")
    L.append("- **Station CV assumes label stock:** colours/keylines of the prep center's own labels. On real photos it "
             "gave confident wrong answers in the review (fur and film read as barcodes), so uploads are never treated "
             "as calibrated: station CV findings on them are downgraded to UNCERTAIN, and the free vision / OCR "
             "providers are used instead.")
    L.append("- **Barcodes are found by bar texture, not decoded** in station CV, and lighting outside the renderer's "
             "range is not yet detected with a reference patch. Both are open items (review roadmap #11, #12).")
    L.append("- **Font size:** measured from text line height at 80 px/in; observed error about +/-1.5 pt, so "
             "measurements within 15% below the requirement are UNCERTAIN, not FAIL.")
    L.append("- **No OCR in station CV:** expiry *format* (MM-DD-YYYY / MM-YYYY) is only checked when the Claude "
             "provider transcribes the date.")
    REPORT_PATH.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
