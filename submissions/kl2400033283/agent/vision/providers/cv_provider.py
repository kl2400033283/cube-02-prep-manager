"""Station CV engine: deterministic pixel analysis for a calibrated prep gantry.

Works without any model or network. It assumes what a fixed prep station
gives you: a known camera scale (px/in) and the center's own label stock
(white FNSKU labels, white bordered warning panels, pale-yellow date labels,
colour-coded handling stickers). Each detector measures a physical cue:

* barcodes        - dense vertical-bar texture (strong d/dx, weak d/dy)
* FNSKU vs UPC    - Amazon FNSKU labels carry >= 2 text lines under the bars,
                    retail UPCs carry one digit row
* curved surface  - Lambertian fall-off of label brightness across its width
* box edge        - a sharp brightness step inside one label (two faces)
* seam            - packing tape continuing on both sides of the label
* polybag         - translucent haze margin around the product + heat-seal crimp
                    texture (strong d/dy, weak d/dx) along the bag mouth
* warning fold    - warning panel split into fragments by a crease band
* font size       - text line height measured in px, converted with px/in
* expiry          - date label present, intact and sharp

Open-world photos (unknown label stock, arbitrary angles) are routed to the
Claude vision provider instead. The detectors return observations only.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage

from submissions.kl2400033283.agent.config import CV_ENGINE_VERSION, STATION_PX_PER_INCH
from submissions.kl2400033283.agent.schemas.evidence import ImageQuality, Region
from submissions.kl2400033283.agent.vision.observations import CheckObservation, UnitObservation, indeterminate
from submissions.kl2400033283.agent.vision.quality import LoadedImage

MARK_STOCK = {
    "fragile": (200, 30, 40),
    "this_way_up": (235, 135, 20),
    "sold_as_set": (35, 85, 195),
    "team_lift": (150, 40, 190),
}
TAPE_STOCK = (206, 178, 120)

# Ratio of measured text-line ink height to the font's point size in px.
# Calibrated on scenario renders (see eval-report.md); default font ink ~0.9 em.
TEXT_INK_TO_EM = 0.88

Box = Tuple[int, int, int, int]  # x0, y0, x1, y1 inclusive-exclusive


def _components(mask: np.ndarray, min_area: int) -> List[Tuple[Box, int, np.ndarray]]:
    lab, n = ndimage.label(mask)
    out = []
    if n == 0:
        return out
    slices = ndimage.find_objects(lab)
    for i, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        sub = lab[sl] == i
        area = int(sub.sum())
        if area < min_area:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        out.append(((x0, y0, x1, y1), area, sub))
    return out


def _overlap(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _norm(box: Box, w: int, h: int) -> List[float]:
    return [round(box[0] / w, 4), round(box[1] / h, 4), round(box[2] / w, 4), round(box[3] / h, 4)]


def _runs(flags: np.ndarray, min_len: int = 2) -> List[Tuple[int, int]]:
    runs, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start >= min_len:
                runs.append((start, i))
            start = None
    if start is not None and len(flags) - start >= min_len:
        runs.append((start, len(flags)))
    return runs


@dataclass
class _Frame:
    img: LoadedImage
    view: int
    rgb: np.ndarray
    gray: np.ndarray
    sat: np.ndarray
    h: int
    w: int
    bg: float
    bars: np.ndarray
    crimp: np.ndarray
    clipped: np.ndarray
    rgb_i: np.ndarray
    mn: np.ndarray


def _prepare(img: LoadedImage, view: int) -> _Frame:
    rgb, gray = img.rgb, img.gray
    h, w = gray.shape
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    border = np.concatenate([gray[:20].ravel(), gray[-20:].ravel(), gray[:, :20].ravel(), gray[:, -20:].ravel()])
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:] = np.abs(np.diff(gray, axis=1))
    gy[1:, :] = np.abs(np.diff(gray, axis=0))
    sx = ndimage.uniform_filter(gx, size=9)
    sy = ndimage.uniform_filter(gy, size=9)
    bars = (sx > 14) & (sy < 0.35 * sx)
    crimp = (sy > 10) & (sx < 0.3 * sy)
    rgb_i = rgb.astype(np.int16)
    mn = rgb_i.min(axis=2)
    clipped = mn >= 253
    return _Frame(img, view, rgb, gray, sat, h, w, float(np.median(border)), bars, crimp, clipped, rgb_i, mn)


_DEFECT_STATES = {"UNSEALED", "OBSCURED", "ON_SEAM", "ON_EDGE", "ON_CURVE", "EXPOSED", "OCCLUDED", "ILLEGIBLE"}


def fuse_views(k: str, obs: List[CheckObservation], order: List[str]) -> CheckObservation:
    """Combine one check across views.

    * A defect seen clearly in any view is a defect (strongest one wins).
    * ABSENT must hold in EVERY view: a label/warning/date sits on one face, so presence in any
      view counts; a view that cannot see (INDETERMINATE) means absence is not proven.
    * A polybag wraps the whole unit, so SEALED in one view and ABSENT in another is a conflict
      between views -> INDETERMINATE (UNCERTAIN), never a FAIL.
    """
    if len(obs) == 1:
        return obs[0]
    defects = [o for o in obs if o.state in _DEFECT_STATES]
    if defects:
        return sorted(defects, key=lambda o: (order.index(o.state), -o.signal))[0]
    states = {o.state for o in obs}
    present = [o for o in obs if o.state not in ("ABSENT", "INDETERMINATE")]
    if "ABSENT" in states and present and k == "polybag_present_sealed":
        views = sorted({r.view_index for o in obs for r in o.regions})
        return CheckObservation(check_key=k, state="INDETERMINATE", signal=0.3,
                                measurements={"view_conflict": True, "views": views},
                                notes=["VIEW_CONFLICT: one view shows a bag, another shows none; "
                                       "a person must check the unit."])
    if present:
        return sorted(present, key=lambda o: (order.index(o.state), -o.signal))[0]
    if states == {"ABSENT"}:
        return max(obs, key=lambda o: o.signal)
    if "ABSENT" in states:  # ABSENT + INDETERMINATE: absence not shown in every view
        return indeterminate(k, "Not found in the views that could be read; at least one view was "
                                "unreadable, so absence is not proven.")
    return max(obs, key=lambda o: o.signal)


class StationCVProvider:
    name = "station_cv"

    def __init__(self, px_per_inch: float = STATION_PX_PER_INCH):
        self.ppi = px_per_inch
        self.model_version = CV_ENGINE_VERSION

    # ------------------------------------------------------------ public
    def observe(self, images: List[LoadedImage], qualities: List[ImageQuality], calibrated: bool,
                context: Optional[Dict] = None) -> UnitObservation:
        per_view: List[Dict[str, CheckObservation]] = []
        for idx, (img, q) in enumerate(zip(images, qualities)):
            if not q.usable:
                continue
            per_view.append(self._observe_frame(_prepare(img, idx), calibrated))
        checks = self._fuse(per_view)
        return UnitObservation(provider=self.name, model_version=self.model_version, checks=checks,
                               model_calls=0, cost_usd=0.0)

    # ------------------------------------------------------------ fusion across views
    _SEVERITY = {
        # Most defect-indicating state wins: a defect seen in any usable view is a defect.
        "polybag_present_sealed": ["UNSEALED", "ABSENT", "SEALED", "SEAL_NOT_VISIBLE", "INDETERMINATE"],
        "suffocation_warning": ["OBSCURED", "LEGIBLE", "ABSENT", "INDETERMINATE"],
        "fnsku_label_placement": ["ON_SEAM", "ON_EDGE", "ON_CURVE", "FLAT", "ABSENT", "INDETERMINATE"],
        "original_barcode_covered": ["EXPOSED", "INDETERMINATE", "COVERED"],
        "expiry_date": ["OCCLUDED", "ILLEGIBLE", "LEGIBLE", "ABSENT", "INDETERMINATE"],
        "handling_marks": ["DETECTED", "INDETERMINATE"],
    }

    def _fuse(self, per_view: List[Dict[str, CheckObservation]]) -> Dict[str, CheckObservation]:
        keys = list(self._SEVERITY.keys())
        if not per_view:
            return {k: indeterminate(k, "No usable image after quality gate") for k in keys}
        fused = {}
        for k in keys:
            obs = [v[k] for v in per_view if k in v]
            if k == "handling_marks":
                marks = sorted({m for o in obs for m in o.measurements.get("detected_marks", [])})
                regions = [r for o in obs for r in o.regions]
                base = obs[0]
                fused[k] = CheckObservation(check_key=k, state=base.state, signal=max(o.signal for o in obs),
                                            measurements={**base.measurements, "detected_marks": marks},
                                            regions=regions, notes=[n for o in obs for n in o.notes])
                continue
            fused[k] = fuse_views(k, obs, self._SEVERITY[k])
        return fused

    # ------------------------------------------------------------ one frame
    def _observe_frame(self, f: _Frame, calibrated: bool) -> Dict[str, CheckObservation]:
        glare_boxes = [b for b, _, _ in _components(f.clipped, 1500)]
        product = self._product_box(f)
        glare_on_product = any(_overlap(g, product) for g in glare_boxes) if product else bool(glare_boxes)

        labels = self._barcode_labels(f)
        out: Dict[str, CheckObservation] = {}
        out["original_barcode_covered"] = self._barcode_check(f, labels, glare_on_product)
        out["fnsku_label_placement"] = self._fnsku_check(f, labels, glare_on_product)
        out["polybag_present_sealed"] = self._polybag_check(f, product)
        out["suffocation_warning"] = self._warning_check(f, labels, glare_on_product, calibrated)
        out["expiry_date"] = self._expiry_check(f, glare_on_product)
        out["handling_marks"] = self._marks_check(f, glare_on_product)
        if glare_boxes:
            for o in out.values():
                o.measurements.setdefault("glare_regions", len(glare_boxes))
        return out

    def _product_box(self, f: _Frame) -> Optional[Box]:
        fg = (np.abs(f.gray - f.bg) > 18) | (f.sat > 30)
        fg = ndimage.binary_opening(fg, iterations=2)
        comps = _components(fg, 20000)
        if not comps:
            return None
        return max(comps, key=lambda c: c[1])[0]

    # ------------------------------------------------------------ barcodes
    def _barcode_labels(self, f: _Frame) -> List[Dict]:
        stock = (f.sat <= 26) & (f.gray >= 125)
        stock_lab, _ = ndimage.label(stock)
        labels = []
        for (x0, y0, x1, y1), area, _ in _components(f.bars, 1200):
            if (x1 - x0) < 25 or (y1 - y0) < 30:
                continue
            # The label stock component that holds this bar blob.
            cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
            ids = stock_lab[max(0, y0 - 6):y1 + 6, max(0, x0 - 6):x1 + 6]
            ids = ids[ids > 0]
            if ids.size == 0:
                continue
            lid = int(np.bincount(ids).argmax())
            # Only look for the label body near its bars so a stray merge cannot run away.
            wx0, wy0 = max(0, x0 - 60), max(0, y0 - 30)
            wx1, wy1 = min(f.w, x1 + 60), min(f.h, y1 + 80)
            ys, xs = np.nonzero(stock_lab[wy0:wy1, wx0:wx1] == lid)
            lbox = (int(xs.min()) + wx0, int(ys.min()) + wy0, int(xs.max()) + 1 + wx0, int(ys.max()) + 1 + wy0)
            # Text lines under the bars, restricted to the bar columns.
            below = f.gray[y1:min(lbox[3] - 2, y1 + 70), x0:x1]
            if below.size == 0:
                labels.append({"bars": (x0, y0, x1, y1), "label": lbox, "label_id": lid,
                               "text_lines": 0, "text_extent_px": 0, "bar_area": area})
                continue
            dark_rows = (below < 150).mean(axis=1) > 0.04
            runs = _runs(dark_rows, 3)
            # FNSKU labels carry a text *block* (code + title/condition) under the bars; a retail UPC carries
            # one digit row. Block height survives defocus better than counting the individual lines.
            extent = (runs[-1][1] - runs[0][0]) if runs else 0
            # Label body below the bars, measured only in the bar columns (so a merged neighbour can't extend it).
            sub = stock_lab[y1:wy1, x0:x1] == lid
            below_px = int(np.median(sub.sum(axis=0))) if sub.size else 0
            text_lines = 2 if (len(runs) >= 2 or extent >= 24 or below_px >= 38) else len(runs)
            labels.append({"bars": (x0, y0, x1, y1), "label": lbox, "label_id": lid,
                           "text_lines": text_lines, "text_extent_px": extent, "bar_area": area})
        return labels

    def _barcode_check(self, f: _Frame, labels: List[Dict], glare: bool) -> CheckObservation:
        k = "original_barcode_covered"
        n = len(labels)
        fnskus = [l for l in labels if l["text_lines"] >= 2]
        others = [l for l in labels if l not in fnskus]
        regions = [Region(view_index=f.view, label="visible barcode", bbox=_norm(l["bars"], f.w, f.h)) for l in labels]
        meas = {"visible_barcodes": n, "fnsku_format_labels": len(fnskus)}
        if n >= 2 or others:
            exposed = others or labels[1:]
            frac = [round(min(1.0, (l["bars"][2] - l["bars"][0]) / 126.0), 2) for l in exposed]
            meas["exposed_width_fraction"] = frac
            return CheckObservation(check_key=k, state="EXPOSED", signal=0.95 if n >= 2 else 0.8,
                                    measurements=meas, regions=regions,
                                    notes=[f"{n} scannable barcode(s) visible; expected exactly one (FNSKU)."])
        if glare:
            return CheckObservation(check_key=k, state="INDETERMINATE", signal=0.2, measurements=meas, regions=regions,
                                    notes=["Specular glare on the product could hide an exposed barcode."])
        return CheckObservation(check_key=k, state="COVERED", signal=0.9, measurements=meas, regions=regions,
                                notes=["Only the FNSKU barcode is visible; no retail barcode detected."] if n else
                                ["No retail barcode visible."])

    def _fnsku_check(self, f: _Frame, labels: List[Dict], glare: bool) -> CheckObservation:
        k = "fnsku_label_placement"
        fnskus = [l for l in labels if l["text_lines"] >= 2]
        if not fnskus:
            if glare:
                return CheckObservation(check_key=k, state="INDETERMINATE", signal=0.2,
                                        notes=["No FNSKU found, but glare covers part of the product."])
            return CheckObservation(check_key=k, state="ABSENT", signal=0.85,
                                    notes=["No label with FNSKU format (bars + text lines) found."])
        lab = max(fnskus, key=lambda l: l["bar_area"])
        x0, y0, x1, y1 = lab["label"]
        bx0, by0, bx1, by1 = lab["bars"]
        region = [Region(view_index=f.view, label="FNSKU label", bbox=_norm(lab["label"], f.w, f.h))]

        # Brightness profile across the label width, from the quiet rows above the bars.
        cx0, cx1 = max(x0, bx0 - 4), min(x1, bx1 + 4)
        band = f.gray[max(y0, by0 - 10):by0 - 2, cx0:cx1] if by0 - 2 > y0 else f.gray[y0:by1, cx0:cx1]
        if band.shape[0] < 2:
            band = f.gray[y0:y1, cx0:cx1]
        prof = np.percentile(band, 90, axis=0)
        prof = ndimage.uniform_filter1d(prof, 5)
        peak = float(prof.max()) or 1.0
        p = prof / peak
        steps = np.abs(p[6:] - p[:-6]) if len(p) > 12 else np.array([0.0])
        step = float(steps.max())
        n = len(p)
        edge_mean = float(min(p[: max(3, n // 10)].mean(), p[-max(3, n // 10):].mean()))
        meas = {"label_width_in": round((x1 - x0) / self.ppi, 2), "brightness_step": round(step, 3),
                "edge_falloff": round(1 - edge_mean, 3)}

        # Seam: packing tape continues on both sides of the label rows.
        tape = np.all(np.abs(f.rgb_i - np.array(TAPE_STOCK, dtype=np.int16)) < np.array([24, 24, 32]), axis=2)
        rows = slice(y0, y1)
        # Windows just outside the label body (bars +/- label margin), so merges cannot shift them.
        lx0, lx1 = bx0 - 30, bx1 + 30
        left = float(tape[rows, max(0, lx0 - 40):max(0, lx0 - 4)].sum())
        right = float(tape[rows, min(f.w, lx1 + 4):min(f.w, lx1 + 40)].sum())
        contact = min(left, right) / 600.0
        meas["tape_contact"] = round(contact, 3)
        if contact > 0.25:
            return CheckObservation(check_key=k, state="ON_SEAM", signal=float(min(0.98, 0.6 + contact / 3)),
                                    measurements=meas, regions=region,
                                    notes=["Packing-tape seam runs under the label on both sides."])
        if step > 0.25:
            return CheckObservation(check_key=k, state="ON_EDGE", signal=min(1.0, 0.5 + step),
                                    measurements=meas, regions=region,
                                    notes=[f"Sharp {step:.0%} brightness step inside the label: it spans two faces (box edge)."])
        if meas["edge_falloff"] > 0.10:
            return CheckObservation(check_key=k, state="ON_CURVE", signal=min(1.0, 0.5 + meas["edge_falloff"]),
                                    measurements=meas, regions=region,
                                    notes=[f"Smooth {meas['edge_falloff']:.0%} brightness fall-off toward the label ends: curved surface."])
        near = f.clipped[max(0, y0 - 40):y1 + 40, max(0, x0 - 40):x1 + 40]
        if glare and near.size and near.mean() > 0.01:
            return CheckObservation(check_key=k, state="INDETERMINATE", signal=0.2, measurements=meas, regions=region,
                                    notes=["Glare on the label prevents geometry assessment."])
        margin = min(0.10 - meas["edge_falloff"], 0.25 - step) / 0.1
        return CheckObservation(check_key=k, state="FLAT", signal=float(np.clip(0.6 + margin, 0.5, 0.99)),
                                measurements=meas, regions=region,
                                notes=["Uniform brightness across the label and no seam contact: flat face."])

    # ------------------------------------------------------------ polybag
    def _polybag_check(self, f: _Frame, product: Optional[Box]) -> CheckObservation:
        k = "polybag_present_sealed"
        if product is None:
            return indeterminate(k, "Product not segmented from background.")
        x0, y0, x1, y1 = product
        ring = np.zeros((f.h, f.w), bool)
        ring[y0 + 30:y1, x0:x1] = True
        ring[y0 + 30 + 10:y1 - 10, x0 + 10:x1 - 10] = False
        lum = f.gray[ring]
        sat = f.sat[ring]
        haze = float(((sat < 22) & (lum > f.bg + 15) & (lum < f.bg + 80)).mean()) if lum.size else 0.0
        # Heat-seal band: the sealed mouth is a bright, unsaturated band along the top of the bag
        # (crimped film reflects strongly). Column-wise brightness survives mild defocus, unlike stripe texture.
        band = slice(y0 + 2, min(f.h, y0 + 24))
        col_lum = f.gray[band, x0:x1].mean(axis=0)
        col_sat = f.sat[band, x0:x1].mean(axis=0)
        seal_cols = (col_lum > f.bg + 70) & (col_sat < 25)
        coverage = float(seal_cols.mean()) if seal_cols.size else 0.0
        crimp_boxes = [1] if coverage > 0.05 else []
        meas = {"haze_margin_fraction": round(haze, 3), "seal_coverage": round(coverage, 3),
                "bag_width_in": round((x1 - x0) / self.ppi, 2)}
        regions = [Region(view_index=f.view, label="polybag", bbox=_norm(product, f.w, f.h))]
        if crimp_boxes:
            regions.append(Region(view_index=f.view, label="heat seal",
                                  bbox=_norm((x0, y0, x1, min(f.h, y0 + 30)), f.w, f.h)))
        bag = haze > 0.5 or (coverage > 0.3 and haze > 0.2)
        if not bag:
            return CheckObservation(check_key=k, state="ABSENT", signal=float(np.clip(1 - haze, 0.5, 0.95)),
                                    measurements=meas, regions=[],
                                    notes=["No translucent film margin or heat seal around the product."])
        if coverage >= 0.9:
            return CheckObservation(check_key=k, state="SEALED", signal=float(np.clip(coverage, 0.5, 0.98)),
                                    measurements=meas, regions=regions,
                                    notes=[f"Heat-seal crimp spans {coverage:.0%} of the bag mouth."])
        if coverage > 0.05:
            gap_in = round((1 - coverage) * (x1 - x0) / self.ppi, 1)
            meas["open_gap_in"] = gap_in
            return CheckObservation(check_key=k, state="UNSEALED", signal=float(np.clip(1.2 - coverage, 0.5, 0.97)),
                                    measurements=meas, regions=regions,
                                    notes=[f"Seal crimp stops after {coverage:.0%} of the mouth; ~{gap_in} in left open."])
        return CheckObservation(check_key=k, state="SEAL_NOT_VISIBLE", signal=0.4, measurements=meas, regions=regions,
                                notes=["Bag film present but the sealed edge is not in this view."])

    # ------------------------------------------------------------ warning panel
    def _white_text_panels(self, f: _Frame, labels: List[Dict]) -> List[Dict]:
        white = (f.mn >= 205) & (f.sat <= 30) & (~f.clipped)
        label_boxes = [l["label"] for l in labels]
        comps = [(box, area) for box, area, _ in _components(white, 600)
                 if not any(_overlap(box, lb) for lb in label_boxes)]
        # Defocused text lines cut a panel into horizontal strips; re-join strips with tiny gaps (< 14 px).
        # A fold/crease band is much taller, so it still separates pieces.
        comps.sort(key=lambda c: c[0][1])
        pieces: List[List] = []
        for box, area in comps:
            for pc in pieces:
                pb = pc[0]
                ox = min(pb[2], box[2]) - max(pb[0], box[0])
                if ox > 0.8 * min(pb[2] - pb[0], box[2] - box[0]) and 0 <= box[1] - pb[3] < 14:
                    pc[0] = (min(pb[0], box[0]), pb[1], max(pb[2], box[2]), max(pb[3], box[3]))
                    pc[1] += area
                    pc[2] = max(pc[2], box[3] - box[1])
                    break
            else:
                pieces.append([box, area, box[3] - box[1]])
        panels = []
        for box, area, tallest in pieces:
            if tallest < 6:
                continue  # stack of 2-px stripes = heat-seal crimp, not a panel
            x0, y0, x1, y1 = box
            # Label-stock prior: warning panels are <= 6 in wide; bag seams/streaks are far wider.
            if area < 2000 or (x1 - x0) > 6 * self.ppi or (y1 - y0) < 18:
                continue
            inner = f.gray[y0 + 3:y1 - 3, x0 + 3:x1 - 3]
            if inner.size == 0:
                continue
            # Print = pixels clearly darker than the panel stock (contrast-relative, survives defocus).
            dark = float((inner < float(np.median(inner)) - 40).mean())
            # Keyline test per side: darkest pixel within 5 px outside the white area must be dark, AND the
            # band 7-11 px out must be clearly brighter (a thin printed line, not a dark product around a sticker).
            g = f.gray
            sides_px = []
            if y0 >= 12:
                sides_px.append((g[y0 - 5:y0, x0:x1].min(axis=0), g[y0 - 11:y0 - 7, x0:x1].mean(axis=0)))
            if y1 + 12 <= f.h:
                sides_px.append((g[y1:y1 + 5, x0:x1].min(axis=0), g[y1 + 7:y1 + 11, x0:x1].mean(axis=0)))
            if x0 >= 12:
                sides_px.append((g[y0:y1, x0 - 5:x0].min(axis=1), g[y0:y1, x0 - 11:x0 - 7].mean(axis=1)))
            if x1 + 12 <= f.w:
                sides_px.append((g[y0:y1, x1:x1 + 5].min(axis=1), g[y0:y1, x1 + 7:x1 + 11].mean(axis=1)))
            keyline_sides = sum(1 for line, outer in sides_px
                                if (line < 95).mean() >= 0.5 and float(np.median(outer - line)) > 25)
            if keyline_sides < 3:
                continue  # printed warning stock has a thin keyline on (at least) three visible sides
            bordered = keyline_sides / 4.0
            panels.append({"box": box, "dark": dark, "area": area, "bordered": bordered})
        return panels

    def _warning_check(self, f: _Frame, labels, glare: bool, calibrated: bool) -> CheckObservation:
        k = "suffocation_warning"
        panels = self._white_text_panels(f, labels)
        if not panels:
            if glare:
                return CheckObservation(check_key=k, state="INDETERMINATE", signal=0.2,
                                        notes=["No warning panel found, but glare covers part of the bag."])
            return CheckObservation(check_key=k, state="ABSENT", signal=0.85,
                                    notes=["No printed text panel found on the bag face."])
        # Group fragments of the same panel (a fold splits one panel into stacked pieces).
        panels.sort(key=lambda p: p["box"][1])
        groups: List[List[Dict]] = []
        for p in panels:
            for g in groups:
                gb = g[-1]["box"]
                ox = min(gb[2], p["box"][2]) - max(gb[0], p["box"][0])
                if ox > 0.7 * min(gb[2] - gb[0], p["box"][2] - p["box"][0]) and 0 <= p["box"][1] - gb[3] < 90:
                    g.append(p)
                    break
            else:
                groups.append([p])
        groups = [gr for gr in groups if max(p["dark"] for p in gr) >= 0.004]
        if not groups:
            return CheckObservation(check_key=k, state="ABSENT", signal=0.7,
                                    notes=["Bordered panel found but no printed text in it."])
        g = max(groups, key=lambda gr: sum(p["area"] for p in gr))
        x0 = min(p["box"][0] for p in g); y0 = min(p["box"][1] for p in g)
        x1 = max(p["box"][2] for p in g); y1 = max(p["box"][3] for p in g)
        region = [Region(view_index=f.view, label="suffocation warning", bbox=_norm((x0, y0, x1, y1), f.w, f.h))]
        meas = {"fragments": len(g), "panel_width_in": round((x1 - x0) / self.ppi, 2)}
        if len(g) > 1:
            gaps = [g[i + 1]["box"][1] - g[i]["box"][3] for i in range(len(g) - 1)]
            meas["occluded_band_in"] = round(max(gaps) / self.ppi, 2)
            return CheckObservation(check_key=k, state="OBSCURED", signal=0.9, measurements=meas, regions=region,
                                    notes=[f"Warning panel is split by a {meas['occluded_band_in']} in fold/crease band; "
                                           "part of the text is hidden."])
        # Text line height -> point size.
        inner = f.gray[y0 + 4:y1 - 4, x0 + 6:x1 - 6]
        rows = (inner < float(np.median(inner)) - 40).mean(axis=1) > 0.01
        runs = _runs(rows, 2)
        if runs and calibrated:
            ink_px = float(np.median([b - a for a, b in runs]))
            pt = ink_px / self.ppi * 72.0 / TEXT_INK_TO_EM
            meas["text_lines"] = len(runs)
            meas["est_font_pt"] = round(pt, 1)
        elif not calibrated:
            meas["est_font_pt"] = None
        sharp = float(ndimage.laplace(inner).var()) if inner.size else 0.0
        meas["panel_sharpness"] = round(sharp, 1)
        return CheckObservation(check_key=k, state="LEGIBLE", signal=0.9, measurements=meas, regions=region,
                                notes=[f"Unbroken warning panel with {len(runs)} text lines."])

    # ------------------------------------------------------------ expiry
    def _expiry_check(self, f: _Frame, glare: bool) -> CheckObservation:
        k = "expiry_date"
        r, g, b = f.rgb[..., 0], f.rgb[..., 1], f.rgb[..., 2]
        patch = (r > 232) & (g > 215) & (b < 215) & ((r - b) > 40) & ((g - b) > 25)
        comps = _components(patch, 600)
        if not comps:
            if glare:
                return CheckObservation(check_key=k, state="INDETERMINATE", signal=0.2,
                                        notes=["No date label found, but glare covers part of the product."])
            return CheckObservation(check_key=k, state="ABSENT", signal=0.8, notes=["No date label found on the captured face."])
        # Pieces of one label split by something stuck across it share the same rows.
        comps.sort(key=lambda c: -c[1])
        anchor = comps[0][0]
        pieces = [c for c in comps if min(c[0][3], anchor[3]) - max(c[0][1], anchor[1]) > 0.6 * (anchor[3] - anchor[1])
                  and (c[0][0] - anchor[2] < 170 and anchor[0] - c[0][2] < 170)]
        x0 = min(c[0][0] for c in pieces); y0 = min(c[0][1] for c in pieces)
        x1 = max(c[0][2] for c in pieces); y1 = max(c[0][3] for c in pieces)
        box = (x0, y0, x1, y1)
        area = sum(c[1] for c in pieces)
        fill = area / float((x1 - x0) * (y1 - y0))
        inner = f.gray[y0:y1, x0:x1]
        ink = float((inner < 150).mean())
        sharp = float(ndimage.laplace(inner).var())
        occluder = float(((f.rgb[y0:y1, x0:x1].min(axis=2) >= 225) & (f.sat[y0:y1, x0:x1] < 20)).mean())
        meas = {"label_fill": round(fill, 3), "ink_fraction": round(ink, 3), "text_sharpness": round(sharp, 1),
                "occluder_fraction": round(occluder, 3), "format_check": "not_performed (station CV has no OCR)"}
        region = [Region(view_index=f.view, label="expiry date", bbox=_norm(box, f.w, f.h))]
        if occluder > 0.15:
            return CheckObservation(check_key=k, state="OCCLUDED", signal=float(np.clip(0.5 + occluder, 0.5, 0.95)),
                                    measurements=meas, regions=region,
                                    notes=[f"A label covers {occluder:.0%} of the date area; the date is not fully visible."])
        if sharp < 100 or ink < 0.005:
            return CheckObservation(check_key=k, state="ILLEGIBLE", signal=0.8, measurements=meas, regions=region,
                                    notes=["Date label found but the print is smeared / too soft to read."])
        return CheckObservation(check_key=k, state="LEGIBLE", signal=0.88, measurements=meas, regions=region,
                                notes=["Intact date label with crisp print."])

    # ------------------------------------------------------------ handling marks
    def _marks_check(self, f: _Frame, glare: bool) -> CheckObservation:
        k = "handling_marks"
        found, regions = [], []
        for mark, col in MARK_STOCK.items():
            # Saturated pixels only: sticker stock is far more saturated than film/labels.
            mask = (f.sat > 90) & (np.abs(f.rgb_i - np.array(col, dtype=np.int16)).max(axis=2) < 28)
            comps = [c for c in _components(mask, 3000)]
            if comps:
                found.append(mark)
                box = max(comps, key=lambda c: c[1])[0]
                regions.append(Region(view_index=f.view, label=f"mark: {mark}", bbox=_norm(box, f.w, f.h)))
        return CheckObservation(check_key=k, state="DETECTED", signal=0.9,
                                measurements={"detected_marks": found, "glare_on_product": glare},
                                regions=regions, notes=[f"Detected stickers: {', '.join(found) or 'none'}."])
