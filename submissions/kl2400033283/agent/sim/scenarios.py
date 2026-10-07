"""Demo scenario library: the challenge's test scenarios as station captures.

Each scenario pairs a rendered capture with realistic unit / work-order
metadata. ``expected`` is what a careful human inspector would conclude and
is only used by tests and the UI's "expected" hint - never by the agent.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from submissions.kl2400033283.agent.config import SCENARIO_DIR
from submissions.kl2400033283.agent.sim.scene_renderer import SceneSpec, render_scene


@dataclass
class Scenario:
    scenario_id: str
    title: str
    challenge_case: str
    story: str
    expected: str
    spec: SceneSpec
    unit: Dict = field(default_factory=dict)

    def __post_init__(self):
        # The label in the picture carries this unit's FNSKU, as a real prep line would print it.
        self.spec.fnsku_text = self.unit.get("fnsku", self.spec.fnsku_text)

    @property
    def image_path(self) -> Path:
        return SCENARIO_DIR / f"{self.scenario_id}.jpg"

    def ensure_rendered(self) -> Path:
        if not self.image_path.exists():
            render_scene(self.spec, self.image_path)
        return self.image_path

    def public(self) -> Dict:
        return {"scenario_id": self.scenario_id, "title": self.title, "challenge_case": self.challenge_case,
                "story": self.story, "expected": self.expected, "unit": self.unit}


def _unit(uid, sku, category, **kw) -> Dict:
    base = {"unit_id": uid, "sku": sku, "asin": f"B0DEMO{uid[-3:]}", "fnsku": f"X00DEMO{uid[-3:]}",
            "work_order_id": f"WO-{uid[-3:]}", "fba_shipment_id": "FBA-DEMO-2610", "category": category,
            "wo_polybag": False, "wo_suffocation_warning": False, "wo_expiry_date": False, "wo_handling_marks": []}
    base.update(kw)
    return base


SCENARIOS: List[Scenario] = [
    Scenario("all-checks-pass", "Fully compliant unit (all 6 checks)", "Correct preparation: every check",
             "Sold-as-set multipack in a sealed polybag: warning, flat FNSKU over the UPC, legible expiry, "
             "SOLD AS SET + FRAGILE stickers. Every one of the six checks applies and passes.", "PASS",
             SceneSpec("UNIT-PASS-01", 500, "box", "sealed", "ok", 14, "flat", "covered", "legible",
                       marks=["sold_as_set", "fragile"]),
             _unit("UNIT-PASS-01", "SET-PLUSH-3PK", "set_multipack", fnsku="X00PASS001", wo_polybag=True,
                   wo_suffocation_warning=True, wo_expiry_date=True, wo_handling_marks=["sold_as_set", "fragile"],
                   bag_length_in=14, bag_width_in=12, bag_opening_in=12, polybag_spec_mil=2.0)),
    Scenario("sealed-polybag", "Plush toy, sealed polybag", "Correctly sealed polybag",
             "Plush bear bagged, heat-sealed edge to edge, warning printed, FNSKU on the bag face.", "PASS",
             SceneSpec("UNIT-S01", 101, "soft", "sealed", "ok", 14, "flat", "covered"),
             _unit("UNIT-S01", "PLUSH-BEAR-12", "plush_toy", wo_polybag=True, wo_suffocation_warning=True,
                   bag_length_in=14, bag_width_in=12, bag_opening_in=12, polybag_spec_mil=1.5)),
    Scenario("missing-warning", "Apparel bag without warning", "Missing warning",
             "T-shirt bagged and sealed, but the bag stock has no suffocation warning.", "FAIL",
             SceneSpec("UNIT-S02", 102, "box", "sealed", "none", 14, "flat", "covered"),
             _unit("UNIT-S02", "TEE-NAVY-M", "apparel_textile", wo_polybag=True, wo_suffocation_warning=True,
                   bag_length_in=16, bag_width_in=12, bag_opening_in=12, polybag_spec_mil=2.0)),
    Scenario("obscured-warning", "Warning folded into a crease", "Obscured warning",
             "Bag was folded over to fit the tote; the crease hides the middle of the warning.", "FAIL",
             SceneSpec("UNIT-S03", 103, "box", "sealed", "folded", 14, "flat", "covered"),
             _unit("UNIT-S03", "TOWEL-SET-2", "apparel_textile", wo_polybag=True, wo_suffocation_warning=True,
                   bag_length_in=14, bag_width_in=12, bag_opening_in=12, polybag_spec_mil=1.5)),
    Scenario("fnsku-on-curve", "Label wrapped round a bottle", "Incorrect FNSKU placement",
             "FNSKU applied across the curve of a 750 ml bottle - scanners lose the bars at the ends.", "FAIL",
             SceneSpec("UNIT-S04", 104, "bottle", "none", "none", 14, "curve", "covered"),
             _unit("UNIT-S04", "BOTTLE-750", "liquid")),
    Scenario("fnsku-on-seam", "FNSKU across the tape seam", "FNSKU on a seam",
             "Label stuck straight over the flap seam; it tears or wrinkles when the box flexes.", "FAIL",
             SceneSpec("UNIT-S05", 105, "box", "none", "none", 14, "seam", "covered"),
             _unit("UNIT-S05", "LAMP-LED-01", "general")),
    Scenario("barcode-visible", "Retail UPC peeking out", "Original barcode visible",
             "FNSKU placed slightly left; a third of the manufacturer UPC is still scannable.", "FAIL",
             SceneSpec("UNIT-S06", 106, "box", "none", "none", 14, "flat", "partial"),
             _unit("UNIT-S06", "CABLE-USBC-2M", "general")),
    Scenario("covered-expiry", "Expiry hidden under a sticker", "Covered expiry date",
             "Whey protein tub; a blank label was stuck over the printed expiry.", "FAIL",
             SceneSpec("UNIT-S07", 107, "box", "none", "none", 14, "flat", "covered", "covered"),
             _unit("UNIT-S07", "WHEY-1KG", "consumable_dated", wo_expiry_date=True)),
    Scenario("missing-handling-mark", "THIS WAY UP sticker missing", "Missing handling mark",
             "Work order asks for FRAGILE and THIS WAY UP; only FRAGILE was applied.", "FAIL",
             SceneSpec("UNIT-S08", 108, "box", "none", "none", 14, "flat", "covered", marks=["fragile"]),
             _unit("UNIT-S08", "VASE-GLASS-30", "fragile_glass", wo_handling_marks=["fragile", "this_way_up"])),
    Scenario("correct-prep", "Dated multipack, fully compliant", "Correct preparation",
             "Sold-as-set snack multipack: date visible, set label + fragile sticker, single barcode.", "PASS",
             SceneSpec("UNIT-S09", 109, "box", "none", "none", 14, "flat", "covered", "legible",
                       marks=["sold_as_set", "fragile"]),
             _unit("UNIT-S09", "SNACK-6PK", "set_multipack", wo_expiry_date=True,
                   wo_handling_marks=["sold_as_set", "fragile"])),
    Scenario("ambiguous-glare", "Glare over the label", "Visually ambiguous preparation",
             "Overhead light reflects off the label area; a hidden UPC cannot be ruled out.", "UNCERTAIN",
             SceneSpec("UNIT-S10", 110, "box", "none", "none", 14, "flat", "covered", optics="glare"),
             _unit("UNIT-S10", "SPEAKER-BT", "general")),
    Scenario("undersized-warning", "Warning print too small for the bag", "Warning legibility (size)",
             "Large 28x34 in comforter bag needs 24 pt; the stock bag prints the warning at 14 pt.", "FAIL",
             SceneSpec("UNIT-S11", 111, "box", "sealed", "ok", 14, "flat", "covered"),
             _unit("UNIT-S11", "COMFORTER-Q", "apparel_textile", wo_polybag=True, wo_suffocation_warning=True,
                   bag_length_in=34, bag_width_in=28, bag_opening_in=28, polybag_spec_mil=2.0)),
    Scenario("blurred-capture", "Motion-blurred capture", "Visually ambiguous preparation",
             "Conveyor moved during exposure. The agent refuses to judge and skips the model call.", "UNCERTAIN",
             SceneSpec("UNIT-S12", 112, "box", "sealed", "ok", 14, "flat", "covered", optics="blur"),
             _unit("UNIT-S12", "HOODIE-L", "apparel_textile", wo_polybag=True, wo_suffocation_warning=True,
                   bag_length_in=16, bag_width_in=12, bag_opening_in=12)),
    Scenario("work-order-gap", "Work order forgot the polybag", "Work order is not proof",
             "Work order says 'no polybag' for a baby blanket; Amazon requires one. Agent checks anyway.", "FAIL",
             SceneSpec("UNIT-S13", 113, "soft", "none", "none", 14, "flat", "covered"),
             _unit("UNIT-S13", "BABY-BLANKET", "baby_product", wo_polybag=False)),
]

BY_ID = {s.scenario_id: s for s in SCENARIOS}


def render_all() -> None:
    for s in SCENARIOS:
        s.ensure_rendered()
