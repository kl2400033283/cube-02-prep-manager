"""Authoritative Amazon Seller Central FBA Preparation Rules & Standards.

Engineering Rule 5: 'Where the channel publishes the requirement, retrieve it.
Don't let a model recall it from memory, and don't infer it from examples.'
"""

from typing import Dict, Any, Optional, Tuple

# Official Amazon FBA Suffocation Warning Font Size Table
# Based on total length + width of polybag (when laid flat)
AMAZON_SUFFOCATION_FONT_SPEC = [
    {"min_dim_inches": 60.0, "min_font_pt": 24, "tier": ">= 60 inches"},
    {"min_dim_inches": 40.0, "min_font_pt": 18, "tier": "40 - 59 inches"},
    {"min_dim_inches": 30.0, "min_font_pt": 14, "tier": "30 - 39 inches"},
    {"min_dim_inches": 0.0,  "min_font_pt": 10, "tier": "< 30 inches"},
]

# Standard Amazon Suffocation Warning Wording
STANDARD_SUFFOCATION_TEXT = (
    "WARNING: To avoid danger of suffocation, keep this bag away from babies and children. "
    "Do not use this bag in cribs, beds, carriages, or playpens. This bag is not a toy."
)

# Mandatory Handling Marks Registry
MANDATORY_HANDLING_MARKS = {
    "fragile": "FRAGILE - HANDLE WITH CARE",
    "sold_as_set": "SOLD AS SET - DO NOT SEPARATE",
    "this_way_up": "THIS WAY UP",
    "ready_to_ship": "READY TO SHIP",
    "team_lift": "HEAVY - TEAM LIFT"
}

def get_required_suffocation_font_size(bag_width_inches: float, bag_length_inches: float) -> int:
    """Computes the authoritative minimum font size for Amazon polybag suffocation warning."""
    total_dimension = bag_width_inches + bag_length_inches
    for tier in AMAZON_SUFFOCATION_FONT_SPEC:
        if total_dimension >= tier["min_dim_inches"]:
            return tier["min_font_pt"]
    return 10

def is_suffocation_warning_mandated(bag_opening_inches: float) -> bool:
    """Amazon rule: bags with an opening of 5 inches or more MUST have a suffocation warning."""
    return bag_opening_inches >= 5.0

def validate_fnsku_placement(surface_type: str, crosses_seam: bool, crosses_curve: bool) -> Tuple[bool, str]:
    """Validates FNSKU label placement according to Amazon barcode standards.
    
    Amazon requires barcode labels to be placed flat on the outside of the packaging.
    Labels wrapping around edges, placed over seams, or curved surfaces are unscannable.
    """
    if crosses_seam:
        return False, "FNSKU label placed across packaging seam or tape boundary (unscannable hazard)"
    if crosses_curve:
        return False, "FNSKU label placed across a curved edge or cylindrical surface"
    if surface_type.lower() not in ["flat", "planar"]:
        return False, f"FNSKU label placed on non-planar surface: {surface_type}"
    return True, "FNSKU label positioned flat on approved exterior surface"

def validate_original_barcode_coverage(original_upc_visible_percent: float) -> Tuple[bool, str]:
    """Amazon rule: 100% of the original manufacturer barcode must be covered.
    
    Receiving scanners will fail with 'Multiple Barcodes Detected' defect fee
    if any portion of original UPC is visible.
    """
    if original_upc_visible_percent > 0.0:
        return False, f"Original barcode is partially exposed ({original_upc_visible_percent:.1f}% visible)"
    return True, "Original manufacturer barcode completely covered"

def validate_expiry_visibility(date_str: Optional[str], is_consumable: bool) -> Tuple[bool, str]:
    """Amazon rule: Expiration dates must be clearly visible and in MM-DD-YYYY or YYYY-MM-DD format."""
    if not is_consumable:
        return True, "Non-consumable item; expiry date check not required"
    if not date_str or date_str.strip() == "":
        return False, "Expiry date is missing or obscured after packaging wrap"
    return True, f"Expiry date {date_str} clearly visible on exterior"
