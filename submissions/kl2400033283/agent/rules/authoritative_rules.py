"""Authoritative prep-requirement registry and requirement resolver.

Engineering Rule 5: the model never decides what the rules are. Every verdict
the agent produces cites a rule from this registry, and every rule records
where it came from:

* ``source="amazon_fba"``  - Amazon Seller Central FBA packaging & prep guidance
  (Polybagging, FBA product barcode labels, Expiration-dated products, Sold-as-set).
* ``source="work_order"``  - a requirement the seller/prep customer put on the
  work order (e.g. a FRAGILE sticker). These are customer requirements, not
  Amazon rules, and the evidence record says so.

Each rule also states whether a 2D photograph can verify it. Requirements that
cannot be verified visually (film thickness, master-carton labelling) become
*attestations* rather than fake visual verdicts.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from submissions.kl2400033283.agent.config import RULES_VERSION

CHECK_KEYS = [
    "polybag_present_sealed",
    "suffocation_warning",
    "fnsku_label_placement",
    "original_barcode_covered",
    "expiry_date",
    "handling_marks",
]

CHECK_TITLES = {
    "polybag_present_sealed": "Polybag present & sealed",
    "suffocation_warning": "Suffocation warning",
    "fnsku_label_placement": "FNSKU label placement",
    "original_barcode_covered": "Original barcode covered",
    "expiry_date": "Expiry date visible",
    "handling_marks": "Handling marks",
}

SOURCE_AMAZON = "amazon_fba"
SOURCE_WORK_ORDER = "work_order"

AMAZON_REF_POLYBAG = "Seller Central > FBA packaging and prep requirements > Polybagging"
AMAZON_REF_LABELS = "Seller Central > FBA product barcode requirements / Labeling requirements"
AMAZON_REF_EXPIRY = "Seller Central > FBA requirements for expiration-dated products"
AMAZON_REF_SETS = "Seller Central > FBA packaging and prep requirements > Sold as sets"

# Provenance (handbook: "retrieve it and record where it came from"). Seller Central help pages render
# client-side, so the full text could not be fetched automatically; what was checked, and how, is recorded.
URL_PREP = "https://sellercentral.amazon.com/gp/help/external/200141500"
URL_EXPIRY = "https://sellercentral.amazon.com/gp/help/external/201003420"
CHECKED = "2026-10-07"
VIA_SEARCH = "requirement values cross-checked by web search on 2026-10-07 (page is client-rendered)"


@dataclass(frozen=True)
class PrepRule:
    rule_id: str
    check_key: Optional[str]          # None for attestation-only rules
    title: str
    requirement: str
    source: str
    source_ref: str
    visually_verifiable: bool
    severity: str = "critical"        # critical -> FAIL blocks shipment
    source_url: Optional[str] = None
    retrieved_on: Optional[str] = None  # date the requirement text was last checked against the source
    retrieval: str = "paraphrased; not re-retrieved by this build"

    def to_dict(self) -> Dict:
        return asdict(self)


RULES: Dict[str, PrepRule] = {r.rule_id: r for r in [
    PrepRule("FBA-PB-01", "polybag_present_sealed", "Polybag is transparent and completely sealed",
             "Items that require polybagging must be in a transparent bag that is completely sealed; "
             "open edges or gaps are not allowed.",
             SOURCE_AMAZON, AMAZON_REF_POLYBAG, True, source_url=URL_PREP, retrieved_on=CHECKED, retrieval=VIA_SEARCH),
    PrepRule("FBA-PB-02", None, "Polybag film thickness >= 1.5 mil",
             "Polybag film must be at least 1.5 mil thick.",
             SOURCE_AMAZON, AMAZON_REF_POLYBAG, False, source_url=URL_PREP, retrieved_on=CHECKED, retrieval=VIA_SEARCH),
    PrepRule("FBA-SW-01", "suffocation_warning", "Suffocation warning on bags with opening >= 5 in",
             "Polybags with an opening of 5 inches or more (measured flat) must carry a suffocation "
             "warning, printed on the bag or applied as a label, in a prominent location.",
             SOURCE_AMAZON, AMAZON_REF_POLYBAG, True, source_url=URL_PREP, retrieved_on=CHECKED, retrieval=VIA_SEARCH),
    PrepRule("FBA-SW-02", "suffocation_warning", "Suffocation warning minimum print size",
             "Warning print size by bag length + width: >= 60 in -> 24 pt; 40-59 in -> 18 pt; "
             "30-39 in -> 14 pt; < 30 in -> 10 pt.",
             SOURCE_AMAZON, AMAZON_REF_POLYBAG, True, source_url=URL_PREP, retrieved_on=CHECKED, retrieval=VIA_SEARCH),
    PrepRule("FBA-LB-01", "fnsku_label_placement", "FNSKU label on a flat surface",
             "The FNSKU barcode label must sit flat on the exterior of the unit; it must not wrap "
             "around curves, corners/edges, or cross seams where it cannot be scanned.",
             SOURCE_AMAZON, AMAZON_REF_LABELS, True, source_url=URL_PREP, retrieved_on=None, retrieval="paraphrased; not re-retrieved by this build"),
    PrepRule("FBA-LB-02", "original_barcode_covered", "Only one scannable barcode",
             "Any original manufacturer barcode (UPC/EAN) must be fully covered so the FNSKU is the "
             "only scannable barcode on the unit. (Units shipped commingled under the manufacturer "
             "barcode are out of scope: this station prep always applies an FNSKU.)",
             SOURCE_AMAZON, AMAZON_REF_LABELS, True, source_url=URL_PREP, retrieved_on=None, retrieval="paraphrased; not re-retrieved by this build"),
    PrepRule("FBA-EX-01", "expiry_date", "Expiration date visible on the unit",
             "Expiration-dated products must show the expiration date on each unit, outside any "
             "polybag/bubble-wrap prep, in MM-DD-YYYY or MM-YYYY format.",
             SOURCE_AMAZON, AMAZON_REF_EXPIRY, True, source_url=URL_EXPIRY, retrieved_on=CHECKED, retrieval=VIA_SEARCH),
    PrepRule("FBA-EX-02", None, "Expiration date on master carton in 36 pt+",
             "The master carton must show the expiration date in 36-point font or larger. "
             "This station photographs units, not cartons.",
             SOURCE_AMAZON, AMAZON_REF_EXPIRY, False, source_url=URL_EXPIRY, retrieved_on=CHECKED, retrieval=VIA_SEARCH),
    PrepRule("FBA-SET-01", "handling_marks", "Sets carry a 'Sold as set' label",
             "Products sold as a set must be labelled 'Sold as set' / 'This is a set. Do not separate.'",
             SOURCE_AMAZON, AMAZON_REF_SETS, True, source_url=URL_PREP, retrieved_on=None, retrieval="paraphrased; not re-retrieved by this build"),
    PrepRule("WO-HM-01", "handling_marks", "Work-order handling marks applied",
             "Handling stickers requested on the work order (FRAGILE, THIS WAY UP, TEAM LIFT) must "
             "be present and visible. Customer requirement, not an Amazon rule.",
             SOURCE_WORK_ORDER, "Prep-center work order", True, severity="major"),
    PrepRule("FBA-LQ-01", None, "Liquids: leak-proof seal / bagging for containers",
             "Liquid containers need a leak-proof closure (double seal / cap tape), and fragile or loose-cap "
             "containers are bagged. A photo cannot prove a seal is leak-proof.",
             SOURCE_AMAZON, AMAZON_REF_POLYBAG, False, source_url=URL_PREP),
    PrepRule("FBA-GL-01", None, "Glass / fragile: protective prep",
             "Fragile and glass items must be prepped (e.g. bubble wrap or box) to survive a drop test. "
             "Drop-test survival cannot be proven from a photo.",
             SOURCE_AMAZON, AMAZON_REF_POLYBAG, False, source_url=URL_PREP),
]}

# Suffocation warning print-size table (FBA-SW-02).
SUFFOCATION_FONT_TABLE = [
    (60.0, 24),
    (40.0, 18),
    (30.0, 14),
    (0.0, 10),
]

SUFFOCATION_WARNING_TEXT = (
    "WARNING: To avoid danger of suffocation, keep this plastic bag away from babies and children. "
    "Do not use this bag in cribs, beds, carriages or play pens. This bag is not a toy."
)

HANDLING_MARKS = {
    "fragile": "FRAGILE - HANDLE WITH CARE",
    "this_way_up": "THIS WAY UP",
    "sold_as_set": "SOLD AS SET - DO NOT SEPARATE",
    "team_lift": "HEAVY - TEAM LIFT",
}

# Product category -> requirements Amazon attaches to that category.
# Only requirements we can cite are listed; everything else comes from the work order.
CATEGORY_PROFILES: Dict[str, Dict] = {
    "general": {"label": "General merchandise", "polybag": False, "expiry": False, "set": False},
    "apparel_textile": {"label": "Apparel / fabric / textile", "polybag": True, "expiry": False, "set": False},
    "plush_toy": {"label": "Plush toy", "polybag": True, "expiry": False, "set": False},
    "baby_product": {"label": "Baby product", "polybag": True, "expiry": False, "set": False},
    "small_item": {"label": "Small item (< 2 1/8 in)", "polybag": True, "expiry": False, "set": False},
    "consumable_dated": {"label": "Expiration-dated consumable", "polybag": False, "expiry": True, "set": False},
    "topical_dated": {"label": "Expiration-dated topical", "polybag": False, "expiry": True, "set": False},
    "liquid": {"label": "Liquid in container", "polybag": False, "expiry": False, "set": False},
    "fragile_glass": {"label": "Glass / fragile", "polybag": False, "expiry": False, "set": False},
    "set_multipack": {"label": "Sold-as-set multipack", "polybag": False, "expiry": False, "set": True},
}


def required_warning_font_pt(bag_length_in: float, bag_width_in: float) -> int:
    total = bag_length_in + bag_width_in
    for threshold, pt in SUFFOCATION_FONT_TABLE:
        if total >= threshold:
            return pt
    return 10


def is_suffocation_warning_mandated(bag_opening_in: float) -> bool:
    return bag_opening_in >= 5.0


def is_valid_expiry_format(text: str) -> bool:
    """MM-DD-YYYY or MM-YYYY (FBA-EX-01). '/' separators are tolerated."""
    from datetime import datetime
    t = text.strip().replace("/", "-")
    try:
        datetime.strptime(t, "%m-%d-%Y")
        return True
    except ValueError:
        pass
    try:
        datetime.strptime(t, "%m-%Y")
        return True
    except ValueError:
        pass
    return False


# ------------------------------------------------------------------ resolver
@dataclass
class Requirement:
    check_key: str
    required: bool
    rule_ids: List[str]
    required_by: List[str]                      # ["amazon_fba", "work_order"]
    params: Dict = field(default_factory=dict)  # e.g. min_font_pt, marks
    note: str = ""


@dataclass
class Attestation:
    rule_id: str
    title: str
    status: str          # ATTESTED_BY_DOCUMENT | DOCUMENT_REQUIRED
    detail: str


@dataclass
class Discrepancy:
    code: str
    check_key: str
    detail: str


@dataclass
class RequirementPlan:
    requirements: Dict[str, Requirement]
    attestations: List[Attestation]
    discrepancies: List[Discrepancy]
    rules_version: str = RULES_VERSION


def resolve_requirements(
    category: str,
    wo_polybag: bool,
    wo_suffocation_warning: bool,
    wo_expiry_date: bool,
    wo_handling_marks: List[str],
    bag_length_in: Optional[float],
    bag_width_in: Optional[float],
    bag_opening_in: Optional[float],
    polybag_spec_mil: Optional[float],
) -> RequirementPlan:
    """Combine what Amazon requires for the category with what the work order asks.

    The work order says what the prep center *intended*. The category rules say
    what Amazon *requires*. When they disagree the stricter one wins and the gap
    is recorded as a discrepancy so the prep center can fix its work orders.
    """
    profile = CATEGORY_PROFILES.get(category, CATEGORY_PROFILES["general"])
    reqs: Dict[str, Requirement] = {}
    discrepancies: List[Discrepancy] = []
    attestations: List[Attestation] = []

    def merge(check_key: str, by_rule: bool, by_wo: bool, rule_ids: List[str], params=None, note=""):
        required_by = []
        if by_rule:
            required_by.append(SOURCE_AMAZON)
        if by_wo:
            required_by.append(SOURCE_WORK_ORDER)
        reqs[check_key] = Requirement(check_key, bool(required_by), rule_ids if required_by else [],
                                      required_by, params or {}, note)
        if by_rule and not by_wo:
            discrepancies.append(Discrepancy(
                "WORK_ORDER_OMITS_REQUIREMENT", check_key,
                f"Category '{profile['label']}' requires this ({', '.join(rule_ids)}) but the work order "
                f"does not ask for it. Checked anyway."))

    # Polybag
    polybag_needed = profile["polybag"] or wo_polybag
    merge("polybag_present_sealed", profile["polybag"], wo_polybag, ["FBA-PB-01"])

    # Suffocation warning: conditional on bag opening size.
    warn_params: Dict = {}
    warn_note = ""
    if polybag_needed:
        if bag_opening_in is not None:
            warn_by_rule = is_suffocation_warning_mandated(bag_opening_in)
            warn_note = f"Bag opening {bag_opening_in:g} in -> warning {'required' if warn_by_rule else 'not required'} (FBA-SW-01)."
        else:
            warn_by_rule = True
            warn_note = "Bag opening not supplied; warning treated as required (conservative)."
        if bag_length_in and bag_width_in:
            warn_params["min_font_pt"] = required_warning_font_pt(bag_length_in, bag_width_in)
            warn_params["bag_length_plus_width_in"] = bag_length_in + bag_width_in
    else:
        warn_by_rule = False
    merge("suffocation_warning", warn_by_rule, wo_suffocation_warning and polybag_needed,
          ["FBA-SW-01", "FBA-SW-02"], warn_params, warn_note)
    if wo_suffocation_warning and not polybag_needed:
        discrepancies.append(Discrepancy("WORK_ORDER_INCONSISTENT", "suffocation_warning",
                                         "Work order asks for a suffocation warning but no polybag."))

    # FNSKU + original barcode: every FBA unit.
    reqs["fnsku_label_placement"] = Requirement("fnsku_label_placement", True, ["FBA-LB-01"], [SOURCE_AMAZON])
    reqs["original_barcode_covered"] = Requirement("original_barcode_covered", True, ["FBA-LB-02"], [SOURCE_AMAZON])

    # Expiry
    merge("expiry_date", profile["expiry"], wo_expiry_date, ["FBA-EX-01"])

    # Handling marks: Amazon 'sold as set' + work-order stickers.
    marks = sorted({m for m in (wo_handling_marks or []) if m in HANDLING_MARKS})
    rule_ids: List[str] = []
    required_by: List[str] = []
    if profile["set"]:
        rule_ids.append("FBA-SET-01")
        required_by.append(SOURCE_AMAZON)
        if "sold_as_set" not in marks:
            discrepancies.append(Discrepancy("WORK_ORDER_OMITS_REQUIREMENT", "handling_marks",
                                             "Set/multipack requires a 'Sold as set' label (FBA-SET-01); "
                                             "work order did not list it. Checked anyway."))
            marks.append("sold_as_set")
    if any(m != "sold_as_set" for m in marks) or ("sold_as_set" in marks and not profile["set"]):
        rule_ids.append("WO-HM-01")
        required_by.append(SOURCE_WORK_ORDER)
    reqs["handling_marks"] = Requirement("handling_marks", bool(marks), rule_ids, required_by,
                                         {"marks": sorted(set(marks))})

    # Attestations: requirements a photo cannot verify.
    if polybag_needed:
        if polybag_spec_mil is not None and polybag_spec_mil >= 1.5:
            attestations.append(Attestation("FBA-PB-02", RULES["FBA-PB-02"].title, "ATTESTED_BY_DOCUMENT",
                                            f"Work order cites bag stock spec {polybag_spec_mil:g} mil. "
                                            "Not visually measurable; accepted on document evidence."))
        elif polybag_spec_mil is not None:
            attestations.append(Attestation("FBA-PB-02", RULES["FBA-PB-02"].title, "DOCUMENT_NONCOMPLIANT",
                                            f"Work order cites {polybag_spec_mil:g} mil stock, below 1.5 mil."))
        else:
            attestations.append(Attestation("FBA-PB-02", RULES["FBA-PB-02"].title, "DOCUMENT_REQUIRED",
                                            "Film gauge cannot be measured from a 2D photo. Attach bag "
                                            "supplier spec to close this item."))
    if category == "liquid":
        attestations.append(Attestation("FBA-LQ-01", RULES["FBA-LQ-01"].title, "DOCUMENT_REQUIRED",
                                        "Leak-proof closure is not visually provable; operator must attest the seal."))
    if category == "fragile_glass":
        attestations.append(Attestation("FBA-GL-01", RULES["FBA-GL-01"].title, "DOCUMENT_REQUIRED",
                                        "Protective prep / drop-test survival is not visually provable; attest it."))
    if reqs["expiry_date"].required:
        attestations.append(Attestation("FBA-EX-02", RULES["FBA-EX-02"].title, "OUT_OF_SCOPE_FOR_STATION",
                                        "Master-carton date marking is checked at the pack station, not here."))

    return RequirementPlan(reqs, attestations, discrepancies)


def rules_catalog() -> List[Dict]:
    return [r.to_dict() for r in RULES.values()]


def rule_source(rule_ids: List[str]) -> List[Dict]:
    """payload.rule_source for the Round 3 contract: where each cited rule came from and when."""
    out = []
    for rid in sorted(set(rule_ids)):
        r = RULES.get(rid)
        if r:
            out.append({"rule_id": rid, "source": r.source, "url": r.source_url or r.source_ref,
                        "retrieved_on": r.retrieved_on, "retrieval": r.retrieval})
    return out
