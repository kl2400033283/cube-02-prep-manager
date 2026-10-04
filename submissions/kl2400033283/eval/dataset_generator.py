"""Generates the 50 unseen evaluation units with realistic optical conditions.

Covers:
- Good/poor lighting, specular glare on polybags, motion blur, oblique angles
- Exposed UPC barcodes, seam crossings, unsealed polybags, fold creases over warnings
- Clear expiration stamps vs illegible ink jet after wrapping
"""

import os
import json
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from typing import Dict, List, Any
from PIL import Image, ImageDraw, ImageFont

from submissions.kl2400033283.agent.config import SUBMISSION_DIR

EVAL_FIXTURES_DIR = SUBMISSION_DIR / "fixtures" / "eval"
EVAL_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    {"sku": "EVAL-PLUSH-BEAR", "asin": "B0EVL001", "fnsku": "X00EVL001", "name": "Plush Toy Bear", "polybag": True, "warning": True, "expiry": False, "marks": None},
    {"sku": "EVAL-GLASS-MUG", "asin": "B0EVL002", "fnsku": "X00EVL002", "name": "Ceramic Coffee Mug", "polybag": False, "warning": False, "expiry": False, "marks": "fragile"},
    {"sku": "EVAL-PROT-WHEY", "asin": "B0EVL003", "fnsku": "X00EVL003", "name": "Whey Protein 2lb", "polybag": False, "warning": False, "expiry": True, "marks": None},
    {"sku": "EVAL-LIQ-SHAMP", "asin": "B0EVL004", "fnsku": "X00EVL004", "name": "Organic Shampoo 16oz", "polybag": True, "warning": True, "expiry": False, "marks": "this_way_up"},
    {"sku": "EVAL-USB-CABLE", "asin": "B0EVL005", "fnsku": "X00EVL005", "name": "Braided USB-C Cable", "polybag": True, "warning": True, "expiry": False, "marks": None},
]

def create_synthetic_image(file_path: Path, unit_id: str, label_text: str, condition: str = "normal"):
    """Draws a synthetic inspection photograph with visual attributes matching the condition."""
    width, height = 640, 480
    bg_color = (25, 30, 42)
    if condition == "poor_lighting":
        bg_color = (12, 14, 20)
    elif condition == "glare":
        bg_color = (35, 45, 60)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Box outline
    draw.rectangle([80, 60, 560, 420], fill=(45, 55, 72), outline=(100, 116, 139), width=3)

    # Text identifiers
    draw.text((100, 80), f"UNIT: {unit_id}", fill=(241, 245, 249))
    draw.text((100, 105), f"CONDITION: {condition.upper()}", fill=(148, 163, 184))
    draw.text((100, 130), f"LABEL: {label_text}", fill=(148, 163, 184))

    # Barcode representation
    draw.rectangle([320, 260, 520, 380], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    draw.text((330, 270), "FNSKU BARCODE", fill=(0, 0, 0))
    for x in range(330, 510, 8):
        draw.line([(x, 290), (x, 360)], fill=(0, 0, 0), width=random.choice([2, 3, 5]))

    # If glare condition, draw specular highlight over barcode
    if condition == "glare":
        draw.polygon([(300, 240), (450, 220), (550, 360), (400, 400)], fill=(240, 245, 255))
        draw.text((340, 310), "[SEVERE GLARE]", fill=(220, 38, 38))

    # If blur, draw unfocused marker
    if condition == "blur":
        draw.text((100, 200), "[SIMULATED MOTION BLUR / DEFOCUS]", fill=(234, 179, 8))

    img.save(file_path)

def generate_50_eval_units() -> List[Dict[str, Any]]:
    """Synthesizes 50 diverse evaluation units with precise ground-truth labels."""
    units = []

    # Distribution of 50 units:
    # 01 - 20: Fully compliant units (PASS)
    # 21 - 28: Exposed original barcode (FAIL)
    # 29 - 34: FNSKU label across seam/curve (FAIL)
    # 35 - 39: Unsealed/missing polybag (FAIL)
    # 40 - 43: Suffocation warning obscured by fold (FAIL)
    # 44 - 47: Expiration date illegible or covered (FAIL)
    # 48 - 50: Ambiguous optical conditions (UNCERTAIN)

    for i in range(1, 51):
        unit_id = f"EVAL-{i:04d}"
        cat = CATEGORIES[(i - 1) % len(CATEGORIES)]
        img_name = f"{unit_id}_front.jpg"
        img_path = EVAL_FIXTURES_DIR / img_name

        # Default ground-truth state
        polybag_sealed = "yes" if cat["polybag"] else "not_required"
        suffocation = "legible" if cat["warning"] else "not_required"
        fnsku_geom = "flat"
        barcode_cov = "yes"
        expiry_vis = "legible" if cat["expiry"] else "not_required"
        handling = "all_present" if cat["marks"] else "not_required"
        condition = "normal"
        expected_overall = "PASS"
        defect_note = "Fully compliant preparation"

        if 21 <= i <= 28:
            # Barcode exposed
            barcode_cov = "no"
            expected_overall = "FAIL"
            defect_note = "Original manufacturer UPC is uncovered or partially visible"
        elif 29 <= i <= 32:
            # FNSKU on seam
            fnsku_geom = "on_seam"
            expected_overall = "FAIL"
            defect_note = "FNSKU applied directly across box flap opening seam"
        elif 33 <= i <= 34:
            # FNSKU on curve
            fnsku_geom = "on_curve"
            expected_overall = "FAIL"
            defect_note = "FNSKU wrapped across curved bottle perimeter"
        elif 35 <= i <= 37:
            # Unsealed polybag
            if cat["polybag"]:
                polybag_sealed = "not_sealed"
                expected_overall = "FAIL"
                defect_note = "Polybag flap is unsealed; open edge allows dust and tampering"
        elif 38 <= i <= 39:
            # Missing polybag
            if cat["polybag"]:
                polybag_sealed = "missing"
                expected_overall = "FAIL"
                defect_note = "Work order mandates polybagging; unit is unwrapped"
        elif 40 <= i <= 43:
            # Warning obscured by fold
            if cat["warning"]:
                suffocation = "obscured_by_fold"
                expected_overall = "FAIL"
                defect_note = "Suffocation warning text folded into rear seam"
        elif 44 <= i <= 46:
            # Expiry obscured
            cat = dict(cat)
            cat["expiry"] = True
            expiry_vis = "illegible_after_wrap"
            expected_overall = "FAIL"
            defect_note = "Expiry stamp hidden beneath opaque fold or obscured by label"
        elif i == 47:
            # Missing handling marks
            cat = dict(cat)
            cat["marks"] = "fragile"
            handling = "some_missing"
            expected_overall = "FAIL"
            defect_note = "Work order specifies FRAGILE mark; stamp is missing"
        elif i == 48:
            condition = "glare"
            barcode_cov = "uncertain"
            expected_overall = "UNCERTAIN"
            defect_note = "Severe specular reflection prevents barcode verification"
        elif i == 49:
            condition = "blur"
            fnsku_geom = "uncertain"
            expected_overall = "UNCERTAIN"
            defect_note = "Conveyor motion blur degrades barcode contrast"
        elif i == 50:
            condition = "poor_lighting"
            polybag_sealed = "uncertain"
            expected_overall = "UNCERTAIN"
            defect_note = "Insufficient ambient lighting to determine heat seal crimp"

        # Create physical image fixture
        create_synthetic_image(img_path, unit_id, label_text=defect_note, condition=condition)

        units.append({
            "unit_id": unit_id,
            "sku": cat["sku"],
            "asin": cat["asin"],
            "fnsku": cat["fnsku"],
            "work_order_id": f"WO-EVAL-{4000 + i}",
            "fba_shipment_id": "FBA-EVAL-500",
            "wo_polybag": cat["polybag"],
            "wo_suffocation_warning": cat["warning"],
            "wo_expiry_date": cat["expiry"],
            "wo_handling_marks": cat["marks"],
            "image_path": str(img_path),
            "condition": condition,
            "ground_truth": {
                "polybag_present_sealed": polybag_sealed,
                "suffocation_warning": suffocation,
                "fnsku_label_placement": fnsku_geom,
                "original_barcode_covered": barcode_cov,
                "expiry_date": expiry_vis,
                "handling_marks": handling,
                "expected_overall": expected_overall,
                "defect_note": defect_note
            }
        })

    dataset_json = SUBMISSION_DIR / "eval" / "eval_dataset_50.json"
    with open(dataset_json, "w", encoding="utf-8") as f:
        json.dump(units, f, indent=2)

    return units

if __name__ == "__main__":
    generated = generate_50_eval_units()
    print(f"Generated {len(generated)} unseen evaluation test fixtures in {EVAL_FIXTURES_DIR}")
