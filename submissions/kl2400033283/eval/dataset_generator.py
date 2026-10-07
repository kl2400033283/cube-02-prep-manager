"""Held-out evaluation set: 50 units the detectors were never tuned on.

Seeds 50000+ are reserved for evaluation. Detector thresholds were calibrated
on seeds 1000-9999 and the demo scenarios (101-113) only.

Composition (stratified so every challenge test scenario appears >= 2 times):
  12 fully compliant | 4 missing warning | 4 folded warning | 2 undersized warning
  4 FNSKU on seam | 3 FNSKU across edge | 3 FNSKU on curve | 1 FNSKU missing
  4 retail UPC exposed | 3 polybag unsealed | 2 polybag missing
  3 expiry covered | 2 expiry smudged | 3 handling mark missing
Optics, assigned by seeded shuffle: 34 normal, 6 slight defocus, 4 glare,
3 heavy blur, 3 under-exposed.
"""

import json
import random
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.config import SUBMISSION_DIR
from submissions.kl2400033283.agent.sim.scene_renderer import SceneSpec, render_scene

EVAL_DIR = SUBMISSION_DIR / "fixtures" / "eval"
DATASET_PATH = SUBMISSION_DIR / "eval" / "eval_dataset.json"
SEED_BASE = 50_000

DEFECT_PLAN = (["compliant"] * 12 + ["warning_missing"] * 4 + ["warning_folded"] * 4 + ["warning_small"] * 2
               + ["fnsku_seam"] * 4 + ["fnsku_edge"] * 3 + ["fnsku_curve"] * 3 + ["fnsku_missing"]
               + ["upc_exposed"] * 4 + ["bag_open"] * 3 + ["bag_missing"] * 2
               + ["expiry_covered"] * 3 + ["expiry_smudged"] * 2 + ["mark_missing"] * 3)
OPTICS_PLAN = ["normal"] * 34 + ["soft"] * 6 + ["glare"] * 4 + ["blur"] * 3 + ["dark"] * 3
assert len(DEFECT_PLAN) == 50 and len(OPTICS_PLAN) == 50


def _build(i: int, defect: str, optics: str) -> Dict:
    r = random.Random(SEED_BASE + i)
    uid = f"EVAL-{i:03d}"
    # Decide product family from the defect, then randomise the rest.
    if defect == "fnsku_curve":
        family = "bottle"
    elif defect.startswith(("warning", "bag")):
        family = r.choice(["bagged_box", "bagged_soft"])
    elif defect.startswith("expiry"):
        family = "dated"
    elif defect == "mark_missing":
        family = "marked"
    else:
        family = r.choice(["plain", "bagged_box", "bagged_soft", "dated", "marked", "bottle"]) \
            if defect == "compliant" else r.choice(["plain", "dated", "marked"])

    spec = SceneSpec(uid, SEED_BASE + i, optics=optics)
    unit = {"unit_id": uid, "sku": f"SKU-{uid}", "asin": f"B0{uid[-3:]}EV", "fnsku": f"X00{uid[-3:]}EV",
            "work_order_id": f"WO-{uid}", "fba_shipment_id": "FBA-EVAL-2610", "category": "general",
            "wo_polybag": False, "wo_suffocation_warning": False, "wo_expiry_date": False, "wo_handling_marks": []}

    if family == "bottle":
        spec.product, spec.fnsku = "bottle", "curve"
        unit["category"] = "liquid"
    elif family in ("bagged_box", "bagged_soft"):
        spec.product = "box" if family == "bagged_box" else "soft"
        spec.polybag, spec.warning, spec.warning_font_pt = "sealed", "ok", r.choice([10, 14, 18])
        unit.update(category=r.choice(["apparel_textile", "plush_toy", "baby_product"]), wo_polybag=True,
                    wo_suffocation_warning=True, bag_length_in=14, bag_width_in=12, bag_opening_in=12,
                    polybag_spec_mil=1.5)
    elif family == "dated":
        spec.expiry = "legible"
        unit.update(category=r.choice(["consumable_dated", "topical_dated"]), wo_expiry_date=True)
    elif family == "marked":
        marks = r.sample(["fragile", "this_way_up", "team_lift"], 2)
        spec.marks = list(marks)
        unit.update(category="fragile_glass", wo_handling_marks=list(marks))

    if family == "bottle" and defect == "compliant":
        # A bottle label on the curve is itself a defect, so compliant bottles become plain boxes.
        spec.product, spec.fnsku = "box", "flat"
        unit["category"] = "general"

    defect_map = {
        "warning_missing": ("warning", "none"), "warning_folded": ("warning", "folded"),
        "warning_small": ("warning", "undersized"), "fnsku_seam": ("fnsku", "seam"),
        "fnsku_edge": ("fnsku", "edge"), "fnsku_missing": ("fnsku", "missing"),
        "upc_exposed": ("upc", r.choice(["exposed", "partial"])), "bag_open": ("polybag", "unsealed"),
        "expiry_covered": ("expiry", "covered"), "expiry_smudged": ("expiry", "smudged"),
    }
    if defect in defect_map:
        attr, val = defect_map[defect]
        setattr(spec, attr, val)
    if defect == "bag_missing":
        spec.polybag, spec.warning = "none", "none"
    if defect == "mark_missing":
        spec.marks = spec.marks[:1]
    if spec.fnsku in ("seam", "edge", "missing") and spec.upc == "partial":
        spec.upc = "exposed"
    if spec.product != "box" and spec.fnsku in ("seam", "edge"):
        spec.product = "box"
    return {"unit": unit, "spec": spec.to_dict(), "defect": defect, "optics": optics}


def ground_truth(item: Dict) -> Dict[str, str]:
    """Physical truth per check from the scene spec (what was actually built)."""
    s, u = item["spec"], item["unit"]
    from submissions.kl2400033283.agent.rules.authoritative_rules import resolve_requirements
    plan = resolve_requirements(u["category"], u["wo_polybag"], u["wo_suffocation_warning"], u["wo_expiry_date"],
                                u["wo_handling_marks"], u.get("bag_length_in"), u.get("bag_width_in"),
                                u.get("bag_opening_in"), u.get("polybag_spec_mil"))
    req = {k: r.required for k, r in plan.requirements.items()}
    truth = {
        "polybag_present_sealed": "PASS" if s["polybag"] == "sealed" else "FAIL",
        "suffocation_warning": "PASS" if s["warning"] == "ok" else "FAIL",
        "fnsku_label_placement": "PASS" if s["fnsku"] == "flat" else "FAIL",
        "original_barcode_covered": "PASS" if s["upc"] == "covered" else "FAIL",
        "expiry_date": "PASS" if s["expiry"] == "legible" else "FAIL",
        "handling_marks": "PASS" if set(u["wo_handling_marks"]) <= set(s["marks"]) else "FAIL",
    }
    truth = {k: (v if req[k] else "NOT_REQUIRED") for k, v in truth.items()}
    truth["overall"] = "FAIL" if "FAIL" in truth.values() else "PASS"
    return truth


def generate() -> List[Dict]:
    optics = OPTICS_PLAN[:]
    random.Random(SEED_BASE).shuffle(optics)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for i, (defect, opt) in enumerate(zip(DEFECT_PLAN, optics), start=1):
        item = _build(i, defect, opt)
        path = EVAL_DIR / f"{item['unit']['unit_id']}.jpg"
        render_scene(SceneSpec(**item["spec"]), path)
        item["image"] = str(path.relative_to(SUBMISSION_DIR)).replace("\\", "/")
        item["truth"] = ground_truth(item)
        items.append(item)
    DATASET_PATH.write_text(json.dumps(items, indent=1), encoding="utf-8")
    return items


if __name__ == "__main__":
    data = generate()
    print(f"Generated {len(data)} held-out units in {EVAL_DIR}")
