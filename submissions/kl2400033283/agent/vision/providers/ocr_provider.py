"""Local OCR + barcode perception provider (real photos, no API key, fully offline).

Uses RapidOCR (ONNX text detection + recognition) and zxing-cpp (barcode
decoding). It only reports what *text and barcodes* can prove:

* suffocation warning  - warning wording read on the bag (and transcribed)
* expiry date          - the printed date transcribed, so the rules engine checks its format
* FNSKU                - FNSKU code read or decoded (and compared with the work order)
* original barcode     - a decoded retail UPC/EAN proves an exposed barcode
* handling marks       - FRAGILE / THIS WAY UP / SOLD AS SET / TEAM LIFT read as text

Polybag sealing and label geometry (flat / curve / seam / edge) cannot be
established from text, so those stay INDETERMINATE -> UNCERTAIN. "Absent"
is only claimed when OCR demonstrably worked on the photos (it read other
text) and at least two views were supplied; otherwise absence is
INDETERMINATE, because the item may simply be on a face that wasn't shot.
"""

import re
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

from submissions.kl2400033283.agent.config import OCR_TIMEOUT_MS
from submissions.kl2400033283.agent.schemas.evidence import ImageQuality, Region
from submissions.kl2400033283.agent.vision.observations import CheckObservation, UnitObservation, indeterminate
from submissions.kl2400033283.agent.vision.quality import LoadedImage

ENGINE_VERSION = "local-ocr-1.0 (rapidocr-onnx + zxing-cpp)"
RETAIL_FORMATS = {"EAN13", "EAN8", "UPCA", "UPCE"}
WARNING_KEYS = ("SUFFOCATION", "SUFFOCATE", "AWAYFROMBABIES", "NOTATOY", "PLASTICBAG")
MARK_KEYS = {
    "fragile": ("FRAGILE", "HANDLEWITHCARE"),
    "this_way_up": ("THISWAYUP", "THISSIDEUP"),
    "sold_as_set": ("SOLDASSET", "DONOTSEPARATE", "THISISASET"),
    "team_lift": ("TEAMLIFT", "HEAVY"),
}
FNSKU_RE = re.compile(r"X0[0-9A-Z]{8}")
# Longest forms first: YYYY-MM-DD, MM-DD-YYYY, MM-YYYY (the rules engine then judges the format).
DATE_RE = re.compile(r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}[-/.]\d{4})")
EXP_KEYS = ("EXP", "BESTBY", "BESTBEFORE", "USEBY", "BBE")

_ocr_lock = threading.Lock()
_ocr_engine = None


def _engine():
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        return _ocr_engine


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        import zxingcpp  # noqa: F401
        return True
    except Exception:
        return False


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _px(img: LoadedImage, bbox) -> Tuple[int, int, int, int]:
    h, w = img.gray.shape
    return int(bbox[0] * w), int(bbox[1] * h), int(bbox[2] * w), int(bbox[3] * h)


def bars_above(img: LoadedImage, bbox) -> float:
    """Bar-stripe strength just above a text line: mean |d/dx| over mean |d/dy|.

    Barcode bars are vertical stripes: strong horizontal change, little vertical change (ratio >> 1).
    Plain print or cardboard gives a ratio around 1. Measured: barcode ~6-9, plain text ~0.7."""
    x0, y0, x1, y1 = _px(img, bbox)
    th = max(4, y1 - y0)
    p = img.gray[max(0, y0 - 4 * th):max(0, y0 - 2), max(0, x0):x1]
    if p.shape[0] < 6 or p.shape[1] < 20:
        return 0.0
    gx = float(np.abs(np.diff(p, axis=1)).mean())
    gy = float(np.abs(np.diff(p, axis=0)).mean())
    return gx / max(gy, 1.0) if gx > 10 else 0.0


def label_is_flat(img: LoadedImage, bbox) -> Tuple[bool, Dict]:
    """Is the white label around a text line one clean, evenly lit rectangle?

    A label over an edge shows a brightness step between its halves, a label on a curve a smooth
    fall-off, a label over a seam a dark line across it. Any of these -> not flat (stays UNCERTAIN;
    this test never claims a defect, it only decides whether FLAT can be claimed)."""
    from scipy import ndimage
    g = img.gray
    h, w = g.shape
    x0, y0, x1, y1 = _px(img, bbox)
    tw, th = x1 - x0, y1 - y0
    # generous window so the whole label fits (text can sit anywhere on it)
    X0, Y0 = max(0, x0 - 2 * tw), max(0, y0 - 10 * th)
    X1, Y1 = min(w, x1 + 2 * tw), min(h, y1 + 5 * th)
    win = g[Y0:Y1, X0:X1]
    if win.size < 400:
        return False, {}
    white = win > max(150.0, float(np.percentile(win, 90)) - 35)
    lab, n = ndimage.label(white)
    if n == 0:
        return False, {}
    # the component that surrounds the text line
    cy, cx = (y0 + y1) // 2 - Y0, min(x1 + 3, X1 - 1) - X0
    ring = lab[max(0, cy - th):cy + th, max(0, (x0 - X0) - 6):cx + 6]
    ids, counts = np.unique(ring[ring > 0], return_counts=True)
    if not len(ids):
        return False, {}
    comp = lab == ids[np.argmax(counts)]
    ys, xs = np.nonzero(comp)
    by0, by1, bx0, bx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    box = comp[by0:by1, bx0:bx1]
    vals = win[by0:by1, bx0:bx1]
    fill = float(box.mean())  # holes = printed bars/text; a clean label is still mostly white
    filled = ndimage.binary_fill_holes(box)
    rect = float(filled.mean())  # how rectangular the outline is
    # brightness of the white paper per column / row: a step or a steady slope means not flat
    col = np.array([vals[:, i][box[:, i]].mean() if box[:, i].any() else np.nan for i in range(box.shape[1])])
    row = np.array([vals[j][box[j]].mean() if box[j].any() else np.nan for j in range(box.shape[0])])
    col, row = col[~np.isnan(col)], row[~np.isnan(row)]
    if len(col) < 20 or len(row) < 10:
        return False, {}
    third = len(col) // 3
    lr = abs(float(np.median(col[:third]) - np.median(col[-third:])))
    tb = abs(float(np.median(row[: len(row) // 3]) - np.median(row[-(len(row) // 3):])))
    step = float(np.max(np.abs(np.diff(ndimage.uniform_filter1d(col, 5))))) if len(col) > 6 else 0.0
    seam = _seam_through(g, X0 + bx0, Y0 + by0, X0 + bx1, Y0 + by1, th)
    seam = seam or _continues_past_edge(g, X0 + bx0, Y0 + by0, X0 + bx1, Y0 + by1, th)
    m = {"label_rectangularity": round(rect, 3), "label_white_fill": round(fill, 3),
         "label_lr_brightness_diff": round(lr, 1), "label_tb_brightness_diff": round(tb, 1),
         "label_max_step": round(step, 1), "seam_through_label": seam,
         "label_size_px": [int(bx1 - bx0), int(by1 - by0)]}
    big_enough = (bx1 - bx0) >= 1.1 * tw and (by1 - by0) >= 2 * th
    # Calibrated on the demo scenes + 50 eval renders: flat labels lr/tb <= 0.4, curved labels tb 2.3-3.3
    # (or lr ~9 when the shaded part drops out), labels over an edge/seam caught by the seam tests.
    flat = big_enough and rect >= 0.93 and lr <= 1.5 and tb <= 1.5 and step <= 6 and not seam
    return flat, m


def _band_cols(strip: np.ndarray) -> set:
    """Columns of a strip that differ strongly from the strip's typical surface (tape, seam, flap edge)."""
    if strip.size == 0:
        return set()
    prof = strip.mean(axis=0)
    dev = np.abs(prof - np.median(prof))
    return set(np.nonzero(dev > 25)[0].tolist())


def _continues_past_edge(g: np.ndarray, x0: int, y0: int, x1: int, y1: int, th: int) -> bool:
    """Label bent over a box edge: the part on the other face is shaded, so the bright 'label' stops
    early and the strip beside it does not look like the surface around it. For a label on one flat
    face, the strip just left/right of the label matches the surface above/below at the same columns."""
    h, w = g.shape
    d = max(4, int(1.5 * th))
    for xa, xb in ((max(0, x0 - d - 2), max(0, x0 - 2)), (min(w, x1 + 2), min(w, x1 + 2 + d))):
        if xb - xa < 3:
            continue
        side = g[y0:y1, xa:xb]
        ref = np.concatenate([g[max(0, y0 - d - 2):max(0, y0 - 2), xa:xb].ravel(),
                              g[min(h, y1 + 2):min(h, y1 + 2 + d), xa:xb].ravel()])
        if side.size and ref.size and abs(float(side.mean()) - float(ref.mean())) > 30:
            return True
    return False


def _seam_through(g: np.ndarray, x0: int, y0: int, x1: int, y1: int, th: int) -> bool:
    """A tape band / seam / flap edge that shows directly above AND below the label at the same x runs
    under it. Also checked left/right for horizontal seams."""
    h, w = g.shape
    d = max(4, int(1.5 * th))
    above = g[max(0, y0 - d - 2):max(0, y0 - 2), x0:x1]
    below = g[min(h, y1 + 2):min(h, y1 + 2 + d), x0:x1]
    left = g[y0:y1, max(0, x0 - d - 2):max(0, x0 - 2)].T
    right = g[y0:y1, min(w, x1 + 2):min(w, x1 + 2 + d)].T
    for a, b in ((above, below), (left, right)):
        both = _band_cols(a) & _band_cols(b)
        if len(both) >= 3:
            return True
    return False


class LocalOCRProvider:
    name = "local_ocr"
    timeout_ms = OCR_TIMEOUT_MS

    def __init__(self):
        self.model_version = ENGINE_VERSION

    @property
    def available(self) -> bool:
        return available()

    # ------------------------------------------------------------------ reading
    def _read(self, img: LoadedImage, view: int) -> Tuple[List[Dict], List[Dict]]:
        import zxingcpp
        rgb = img.rgb.astype(np.uint8)
        h, w = rgb.shape[:2]
        lines = []
        result, _ = _engine()(rgb[..., ::-1])  # RapidOCR expects BGR
        for box, text, conf in result or []:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append({"text": text, "norm": _norm(text), "conf": float(conf), "view": view,
                          "bbox": [max(0, min(xs)) / w, max(0, min(ys)) / h, min(w, max(xs)) / w, min(h, max(ys)) / h]})
        codes = []
        for b in zxingcpp.read_barcodes(rgb):
            pos = b.position
            xs = [pos.top_left.x, pos.top_right.x, pos.bottom_left.x, pos.bottom_right.x]
            ys = [pos.top_left.y, pos.top_right.y, pos.bottom_left.y, pos.bottom_right.y]
            codes.append({"format": str(b.format).split(".")[-1].upper().replace("-", ""), "text": b.text, "view": view,
                          "bbox": [min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h]})
        return lines, codes

    def observe(self, images: List[LoadedImage], qualities: List[ImageQuality], calibrated: bool,
                context: Optional[Dict] = None) -> UnitObservation:
        lines, codes = [], []
        n_views = 0
        glare = False
        for idx, (img, q) in enumerate(zip(images, qualities)):
            if not q.usable:
                continue
            n_views += 1
            glare = glare or "GLARE" in q.issues
            l, c = self._read(img, idx)
            lines += l
            codes += c
        ocr_works = len([l for l in lines if l["conf"] >= 0.7]) >= 2
        may_claim_absence = ocr_works and n_views >= 2
        absence_note = ("" if may_claim_absence else
                        " Absence not claimed: needs >= 2 views and readable text elsewhere in the photos.")

        def region(items, label):
            return [Region(view_index=i["view"], label=label, bbox=[round(v, 4) for v in i["bbox"]]) for i in items]

        out: Dict[str, CheckObservation] = {}

        # Suffocation warning
        warn = [l for l in lines if any(k in l["norm"] for k in WARNING_KEYS)]
        if warn:
            text = " ".join(l["text"] for l in sorted(warn, key=lambda l: (l["view"], l["bbox"][1])))
            conf = float(np.mean([l["conf"] for l in warn]))
            # Include neighbouring lines of the same view (the rest of the warning paragraph).
            out["suffocation_warning"] = CheckObservation(
                check_key="suffocation_warning", state="LEGIBLE", signal=round(conf, 3),
                measurements={"warning_text": text[:400], "wording_ok": any("SUFFOCAT" in l["norm"] for l in warn),
                              "est_font_pt": None},
                regions=region(warn, "warning text"),
                notes=[f"Read suffocation warning text (OCR confidence {conf:.2f}); print size not measured (no scale)."])
        elif may_claim_absence:
            out["suffocation_warning"] = CheckObservation(
                check_key="suffocation_warning", state="ABSENT", signal=0.6,
                notes=[f"No warning wording read in {n_views} views although other text was read."])
        else:
            out["suffocation_warning"] = indeterminate("suffocation_warning", "No warning text read." + absence_note)

        # Expiry date
        exp_lines = [l for l in lines if any(k in l["norm"] for k in EXP_KEYS)]
        date_text = None
        for l in exp_lines:
            m = DATE_RE.search(l["text"].replace(" ", ""))
            if m:
                date_text = m.group(1)
                break
        if date_text:
            out["expiry_date"] = CheckObservation(
                check_key="expiry_date", state="LEGIBLE", signal=round(float(np.mean([l["conf"] for l in exp_lines])), 3),
                measurements={"date_text": date_text}, regions=region(exp_lines, "expiry date"),
                notes=[f"Read expiry date '{date_text}'."])
        elif exp_lines:
            out["expiry_date"] = CheckObservation(
                check_key="expiry_date", state="ILLEGIBLE", signal=0.6, regions=region(exp_lines, "expiry date"),
                notes=["An expiry marker was read but the date itself is not legible."])
        elif may_claim_absence:
            out["expiry_date"] = CheckObservation(check_key="expiry_date", state="ABSENT", signal=0.6,
                                                  notes=[f"No expiry date read in {n_views} views."])
        else:
            out["expiry_date"] = indeterminate("expiry_date", "No expiry text read." + absence_note)

        # FNSKU presence / identity (placement geometry is not provable from text)
        fn_codes = [c for c in codes if c["text"].upper().startswith("X0")]
        fn_lines = [l for l in lines if FNSKU_RE.search(l["norm"]) or "FNSKU" in l["norm"]]
        fnsku_text = None
        for src in [c["text"] for c in fn_codes] + [l["norm"] for l in fn_lines]:
            m = FNSKU_RE.search(src.upper())
            if m:
                fnsku_text = m.group(0)
                break
        flat_label = None
        for l in fn_lines:
            ok, geo = label_is_flat(images[l["view"]], l["bbox"])
            if ok:
                flat_label = (l, geo)
                break
        if flat_label:
            l, geo = flat_label
            out["fnsku_label_placement"] = CheckObservation(
                check_key="fnsku_label_placement", state="FLAT", signal=round(min(0.7, l["conf"]), 3),
                measurements={"fnsku_text": fnsku_text or "", **geo},
                regions=region([l], "FNSKU label"),
                notes=[f"FNSKU label ({fnsku_text or 'code read'}) is one clean, evenly lit rectangle with no seam "
                       "or edge running under it."])
        elif fn_codes or fn_lines:
            # Signal = how reliably the code was *read* (decoded barcode ~ certain; else OCR confidence).
            read_conf = 0.97 if fn_codes else float(np.mean([l["conf"] for l in fn_lines]))
            out["fnsku_label_placement"] = CheckObservation(
                check_key="fnsku_label_placement", state="INDETERMINATE", signal=round(read_conf, 3),
                measurements={"fnsku_text": fnsku_text or ""},
                regions=region(fn_codes or fn_lines, "FNSKU label"),
                notes=[f"FNSKU label present ({fnsku_text or 'code not fully read'}); "
                       "flat-face placement can't be judged from text alone."])
        elif may_claim_absence:
            out["fnsku_label_placement"] = CheckObservation(check_key="fnsku_label_placement", state="ABSENT",
                                                            signal=0.6, notes=["No FNSKU code read or decoded."])
        else:
            out["fnsku_label_placement"] = indeterminate("fnsku_label_placement", "No FNSKU read." + absence_note)

        # Original barcode: a decoded retail symbology is positive proof of exposure.
        retail = [c for c in codes if c["format"] in RETAIL_FORMATS]
        # Printed UPC/EAN number (11-14 digits, OCR may add or drop one) with bar stripes right above it.
        printed_retail = []
        for l in lines:
            if l["norm"].isdigit() and 11 <= len(l["norm"]) <= 14 and l["conf"] >= 0.6:
                l["_bars"] = bars_above(images[l["view"]], l["bbox"])
                if l["_bars"] >= 3.0:
                    printed_retail.append(l)
        if retail:
            out["original_barcode_covered"] = CheckObservation(
                check_key="original_barcode_covered", state="EXPOSED", signal=0.97,
                measurements={"visible_barcodes": len(codes), "exposed_barcode_type": retail[0]["format"]},
                regions=region(retail, "retail barcode"),
                notes=[f"Decoded a scannable {retail[0]['format']} retail barcode ({retail[0]['text']})."])
        elif printed_retail:
            l = printed_retail[0]
            out["original_barcode_covered"] = CheckObservation(
                check_key="original_barcode_covered", state="EXPOSED", signal=0.75,
                measurements={"visible_barcodes": len(codes) + len(printed_retail), "retail_number_read": l["text"],
                              "bar_stripe_ratio": round(l["_bars"], 1)},
                regions=region([l], "retail barcode (printed number)"),
                notes=[f"A retail barcode is visible: bars with the printed number '{l['text']}' under them. "
                       "It did not decode, but it is not covered."])
        else:
            out["original_barcode_covered"] = CheckObservation(
                check_key="original_barcode_covered", state="INDETERMINATE", signal=0.3,
                measurements={"visible_barcodes": len(codes)},
                notes=["No retail barcode decoded, but an undecodable or out-of-view one can't be ruled out."])

        # Handling marks
        found = sorted({m for m, keys in MARK_KEYS.items() for l in lines if any(k in l["norm"] for k in keys)})
        mark_lines = [l for l in lines if any(k in l["norm"] for keys in MARK_KEYS.values() for k in keys)]
        if found or may_claim_absence:
            out["handling_marks"] = CheckObservation(
                check_key="handling_marks", state="DETECTED", signal=0.85,
                measurements={"detected_marks": found, "glare_on_product": glare and not found},
                regions=region(mark_lines, "handling mark"),
                notes=[f"Handling text read: {', '.join(found) or 'none'}."])
        else:
            out["handling_marks"] = indeterminate("handling_marks", "No handling text read." + absence_note)

        # Polybag: not provable from text.
        out["polybag_present_sealed"] = indeterminate(
            "polybag_present_sealed",
            "Film presence and seal integrity can't be verified from text; needs a vision model or the station camera.")

        return UnitObservation(provider=self.name, model_version=self.model_version, checks=out,
                               model_calls=0, cost_usd=0.0,
                               raw_notes=[f"OCR lines={len(lines)} barcodes={len(codes)} views={n_views}"])
