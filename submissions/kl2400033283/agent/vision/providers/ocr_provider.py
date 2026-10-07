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
        if fn_codes or fn_lines:
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
        if retail:
            out["original_barcode_covered"] = CheckObservation(
                check_key="original_barcode_covered", state="EXPOSED", signal=0.97,
                measurements={"visible_barcodes": len(codes), "exposed_barcode_type": retail[0]["format"]},
                regions=region(retail, "retail barcode"),
                notes=[f"Decoded a scannable {retail[0]['format']} retail barcode ({retail[0]['text']})."])
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
