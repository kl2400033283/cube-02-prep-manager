"""Synthetic prep-station capture renderer.

Renders a 1280x960 overhead frame (80 px/in) of a prepared unit on a conveyor:
product face, packing-tape seam, manufacturer UPC, FNSKU label, polybag film
with heat-seal crimp, suffocation-warning panel, expiry-date label, handling
stickers, then camera optics (blur, glare, under-exposure) and sensor noise.

Why synthetic: the challenge ships no images. These renders let us test the
full pipeline end-to-end with known ground truth. The station CV engine only
ever sees the pixels; the SceneSpec is used solely as ground truth by the
evaluation harness. Real photographs go through the Claude vision provider.
"""

import random
import textwrap
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from submissions.kl2400033283.agent.rules.authoritative_rules import SUFFOCATION_WARNING_TEXT

W_IMG, H_IMG = 1280, 960
PPI = 80.0

BOX_COLORS = [(140, 52, 58), (46, 86, 140), (62, 112, 76), (96, 70, 140), (30, 120, 125)]
SOFT_COLORS = [(205, 120, 60), (200, 90, 120), (90, 150, 200)]
TAPE = (206, 178, 120)
LABEL_WHITE = (246, 246, 244)
EXPIRY_PATCH = (250, 236, 182)
MARK_COLORS = {
    "fragile": (200, 30, 40),
    "this_way_up": (235, 135, 20),
    "sold_as_set": (35, 85, 195),
    "team_lift": (150, 40, 190),
}
MARK_TEXT = {"fragile": "FRAGILE", "this_way_up": "THIS WAY UP", "sold_as_set": "SOLD AS SET", "team_lift": "TEAM LIFT"}


@dataclass
class SceneSpec:
    unit_id: str
    seed: int = 0
    product: str = "box"            # box | bottle | soft
    polybag: str = "none"           # none | sealed | unsealed
    warning: str = "none"           # none | ok | folded | undersized
    warning_font_pt: float = 14.0
    fnsku: str = "flat"             # flat | seam | curve | edge | missing
    upc: str = "covered"            # covered | exposed | partial
    expiry: str = "none"            # none | legible | covered | smudged
    expiry_text: str = "03-2027"
    marks: List[str] = field(default_factory=list)
    optics: str = "normal"          # normal | soft (slight defocus) | blur | glare | dark
    fnsku_text: str = "X00EVL0001"

    def to_dict(self) -> Dict:
        return asdict(self)


def _font(px: float) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=max(4, int(round(px))))


def _bars(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, rng: random.Random):
    x = x0
    while x < x1:
        w = rng.choice([2, 2, 3, 4])
        if x + w > x1:
            break
        draw.rectangle([x, y0, x + w - 1, y1], fill=(22, 22, 24))
        x += w + rng.choice([2, 3, 4])


def _upc(draw, x, y, rng) -> Tuple[int, int, int, int]:
    w, h = 150, 84
    draw.rectangle([x, y, x + w, y + h], fill=LABEL_WHITE)
    _bars(draw, x + 12, y + 8, x + w - 12, y + h - 22, rng)
    draw.text((x + 22, y + h - 19), "0 12345 67890 5", fill=(30, 30, 30), font=_font(13))
    return (x, y, x + w, y + h)


def _fnsku(draw, fnsku_text, x, y, rng) -> Tuple[int, int, int, int]:
    w, h = 230, 130
    draw.rectangle([x, y, x + w, y + h], fill=LABEL_WHITE)
    _bars(draw, x + 26, y + 12, x + w - 26, y + 76, rng)
    draw.text((x + 30, y + 84), fnsku_text, fill=(25, 25, 25), font=_font(16))
    draw.text((x + 30, y + 104), "New - Prep Mgr", fill=(60, 60, 60), font=_font(12))
    return (x, y, x + w, y + h)


def _blank(draw, x, y, w=170, h=104) -> Tuple[int, int, int, int]:
    draw.rectangle([x, y, x + w, y + h], fill=LABEL_WHITE)
    return (x, y, x + w, y + h)


def _shade_columns(arr: np.ndarray, box: Tuple[int, int, int, int], profile: np.ndarray):
    x0, y0, x1, y1 = box
    arr[y0:y1, x0:x1] *= profile[None, : x1 - x0, None]


def render_scene(spec: SceneSpec, out_path: Optional[Path] = None) -> Tuple[Image.Image, Dict]:
    rng = random.Random(spec.seed)
    nrng = np.random.default_rng(spec.seed)
    layout: Dict[str, Tuple[int, int, int, int]] = {}

    base = np.full((H_IMG, W_IMG, 3), (62, 66, 72), dtype=np.float32)
    img = Image.fromarray(base.astype(np.uint8))
    d = ImageDraw.Draw(img)

    # --------------------------------------------------------- product
    if spec.product == "bottle":
        fw, fh = rng.randint(320, 350), rng.randint(600, 640)
    else:
        fw, fh = rng.randint(680, 740), rng.randint(520, 560)
    fx = rng.randint(190, 250) if spec.product != "bottle" else rng.randint(380, 440)
    fy = rng.randint(170, 200)
    side_w = 90 if spec.product == "box" else 0
    layout["front"] = (fx, fy, fx + fw, fy + fh)

    if spec.product == "box":
        col = rng.choice(BOX_COLORS)
        d.rectangle([fx, fy, fx + fw, fy + fh], fill=col)
        side = tuple(int(c * 0.58) for c in col)
        d.polygon([(fx + fw, fy), (fx + fw + side_w, fy - 40), (fx + fw + side_w, fy + fh - 40), (fx + fw, fy + fh)], fill=side)
        ty = fy + int(fh * rng.uniform(0.42, 0.47))
        d.rectangle([fx, ty, fx + fw, ty + 30], fill=TAPE)
        layout["tape"] = (fx, ty, fx + fw, ty + 30)
    elif spec.product == "bottle":
        col = (60, 140, 170)
        d.rounded_rectangle([fx, fy, fx + fw, fy + fh], radius=60, fill=col)
    else:
        col = rng.choice(SOFT_COLORS)
        d.ellipse([fx, fy, fx + fw, fy + fh], fill=col)

    # Slots relative to the front face
    s_tl = (fx + 30, fy + 40)
    s_tr_x = fx + fw - 30 - 180
    s_bl = (fx + 30, fy + fh - 30 - 56)
    s_br = (fx + fw - 40 - 230, fy + fh - 40 - 130)
    s_bc_x = fx + int(fw * 0.36)

    # --------------------------------------------------------- manufacturer UPC (printed on product)
    if spec.product == "bottle":
        lx, ly = fx + (fw - 230) // 2, fy + int(fh * 0.58)
        upc_xy = (lx + 40, ly + 23)
    elif spec.upc == "exposed" or spec.fnsku == "edge":
        upc_xy = (s_bc_x, s_br[1] + 23)
    else:
        upc_xy = (s_br[0] + 40, s_br[1] + 23)
    layout["upc"] = _upc(d, upc_xy[0], upc_xy[1], rng)

    # --------------------------------------------------------- polybag film
    arr = np.asarray(img, dtype=np.float32).copy()
    if spec.product == "bottle":
        # cylindrical shading across the bottle (and anything printed on it)
        xs = np.linspace(-1.5, 1.5, fw)
        profile = 0.45 + 0.55 * np.cos(xs)
        _shade_columns(arr, (fx, fy, fx + fw, fy + fh), profile.astype(np.float32))
    bag_box = None
    if spec.polybag != "none":
        bx0, by0 = fx - 34, fy - 34 - (40 if side_w else 0)
        bx1, by1 = fx + fw + side_w + 34, fy + fh + 34
        bag_box = (bx0, by0, bx1, by1)
        layout["bag"] = bag_box
        region = arr[by0:by1, bx0:bx1]
        region[:] = region * 0.78 + np.array([236, 240, 246], dtype=np.float32) * 0.22
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    if bag_box:
        bx0, by0, bx1, by1 = bag_box
        d.rectangle([bx0, by0, bx1, by1], outline=(205, 210, 216), width=3)
        for k in range(3):
            sx = bx0 + 80 + k * 220 + rng.randint(-20, 20)
            d.line([(sx, by0 + 40), (sx + 140, by0 + 200)], fill=(196, 202, 210), width=5)
        crimp_w = bx1 - bx0
        if spec.polybag == "unsealed":
            sealed_to = bx0 + int(crimp_w * rng.uniform(0.40, 0.55))
        else:
            sealed_to = bx1
        for row in range(0, 22, 4):
            d.rectangle([bx0, by0 + row, sealed_to, by0 + row + 1], fill=(222, 225, 229))
            d.rectangle([bx0, by0 + row + 2, sealed_to, by0 + row + 3], fill=(140, 144, 150))
        if sealed_to < bx1:
            d.rectangle([sealed_to + 2, by0 - 2, bx1 + 2, by0 + 14], fill=(36, 40, 46))
        layout["crimp"] = (bx0, by0, sealed_to, by0 + 22)

    # --------------------------------------------------------- suffocation warning panel (on bag)
    if spec.warning != "none":
        pt = spec.warning_font_pt if spec.warning != "undersized" else 5.0
        px = pt / 72.0 * PPI
        font = _font(px)
        pw = 330 if pt < 16 else 390
        chars = max(12, int((pw - 24) / (px * 0.55)))
        lines = textwrap.wrap(SUFFOCATION_WARNING_TEXT, chars)
        lh = int(px * 1.3) + 1
        ph = 18 + lh * len(lines) + 10
        wx, wy = s_tl
        if spec.product == "bottle":
            wx, wy = fx - 34 + 6, fy + 40
        d.rectangle([wx, wy, wx + pw, wy + ph], fill=LABEL_WHITE, outline=(20, 20, 20), width=3)
        for i, line in enumerate(lines):
            d.text((wx + 12, wy + 12 + i * lh), line, fill=(18, 18, 18), font=font)
        layout["warning"] = (wx, wy, wx + pw, wy + ph)
        if spec.warning == "folded":
            fy0 = wy + int(ph * rng.uniform(0.30, 0.38))
            fy1 = fy0 + int(ph * rng.uniform(0.30, 0.38))
            d.rectangle([wx - 14, fy0, wx + pw + 14, fy1], fill=(116, 120, 127))
            d.line([(wx - 14, fy0 + 3), (wx + pw + 14, fy0 + 3)], fill=(70, 74, 80), width=3)
            layout["fold"] = (wx - 14, fy0, wx + pw + 14, fy1)

    # --------------------------------------------------------- FNSKU label + UPC cover
    ux, uy = layout["upc"][0], layout["upc"][1]
    if spec.product == "bottle":
        layout["fnsku"] = (lx, ly, lx + 230, ly + 130)
        _fnsku(d, spec.fnsku_text, lx, ly, rng)
    elif spec.fnsku == "flat":
        if spec.upc == "covered":
            layout["fnsku"] = _fnsku(d, spec.fnsku_text, ux - 40, uy - 23, rng)
        elif spec.upc == "partial":
            layout["fnsku"] = _fnsku(d, spec.fnsku_text, ux - 40 - rng.randint(118, 132), uy - 23, rng)
        else:
            layout["fnsku"] = _fnsku(d, spec.fnsku_text, s_br[0], s_br[1], rng)
    elif spec.fnsku == "seam":
        t = layout["tape"]
        layout["fnsku"] = _fnsku(d, spec.fnsku_text, fx + fw - 30 - 240, t[1] - 45, rng)
        if spec.upc == "covered":
            layout["upc_cover"] = _blank(d, ux - 10, uy - 10)
    elif spec.fnsku == "edge":
        lx2, ly2 = fx + fw - 140, fy + int(fh * 0.57)
        layout["fnsku"] = _fnsku(d, spec.fnsku_text, lx2, ly2, rng)
        if spec.upc == "covered":
            layout["upc_cover"] = _blank(d, ux - 10, uy - 10)
    elif spec.fnsku == "missing" and spec.upc == "covered":
        layout["upc_cover"] = _blank(d, ux - 10, uy - 10)

    # --------------------------------------------------------- expiry label
    if spec.expiry != "none":
        ex, ey = s_bl
        if spec.product == "bottle":
            ex, ey = fx + (fw - 200) // 2, fy + int(fh * 0.36)
        d.rectangle([ex, ey, ex + 200, ey + 56], fill=EXPIRY_PATCH)
        d.text((ex + 14, ey + 14), f"EXP {spec.expiry_text}", fill=(35, 30, 25), font=_font(26))
        layout["expiry"] = (ex, ey, ex + 200, ey + 56)
        if spec.expiry == "covered":
            layout["expiry_cover"] = _blank(d, ex + 40, ey - 18, 120, 92)
        elif spec.expiry == "smudged":
            crop = img.crop((ex, ey, ex + 200, ey + 56)).filter(ImageFilter.GaussianBlur(5))
            img.paste(crop, (ex, ey))
            d = ImageDraw.Draw(img)

    # --------------------------------------------------------- handling stickers
    for i, mark in enumerate(spec.marks):
        mx, my = s_tr_x, fy + 36 + i * 70
        if spec.product == "bottle":
            mx, my = fx + (fw - 180) // 2, fy + 30 + i * 72
        c = MARK_COLORS[mark]
        d.rectangle([mx, my, mx + 180, my + 60], fill=c)
        tc = (255, 255, 255) if mark != "this_way_up" else (20, 20, 20)
        d.text((mx + 16, my + 18), MARK_TEXT[mark], fill=tc, font=_font(22))
        layout[f"mark:{mark}"] = (mx, my, mx + 180, my + 60)

    # --------------------------------------------------------- label-on-geometry effects
    arr = np.asarray(img, dtype=np.float32).copy()
    if spec.fnsku == "edge" and spec.product == "box":
        # The part of the label past the box edge lies on the darker side face.
        x0, y0, x1, y1 = layout["fnsku"]
        edge_x = fx + fw
        arr[y0:y1 + 1, edge_x:x1 + 1] *= 0.6
    if spec.product == "bottle":
        x0, y0, x1, y1 = layout["fnsku"]
        xs = np.linspace(-1.5, 1.5, fw)
        prof = (0.45 + 0.55 * np.cos(xs)).astype(np.float32)
        arr[y0:y1 + 1, x0:x1 + 1] *= prof[x0 - fx:x1 + 1 - fx][None, :, None]

    # --------------------------------------------------------- optics
    if spec.optics == "glare":
        target = layout.get("fnsku") or layout["upc"]
        cx, cy = (target[0] + target[2]) // 2, (target[1] + target[3]) // 2
        yy, xx = np.ogrid[:H_IMG, :W_IMG]
        mask = ((xx - cx) / 190.0) ** 2 + ((yy - cy) / 120.0) ** 2
        alpha = np.clip(1.6 - mask, 0, 1)[..., None]
        arr = arr * (1 - alpha) + 255.0 * alpha
    elif spec.optics == "dark":
        arr *= 0.2
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if spec.optics == "blur":
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(4.0, 5.5)))
    elif spec.optics == "soft":
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.2)))
    arr = np.asarray(img, dtype=np.float32) + nrng.normal(0, 2.5, (H_IMG, W_IMG, 3))
    if spec.optics == "glare":
        # sensor clips: glare core stays saturated after noise
        arr = np.where(alpha >= 0.999, 255.0, arr)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, quality=93)
    return img, layout
