"""Image loading and optical quality gate.

The quality gate is deterministic and independent of whichever perception
provider runs afterwards, so it doubles as a cross-check: a provider that
claims to have read small print on a blurred or glare-washed frame gets
downgraded to UNCERTAIN by the rules engine.

Thresholds were set on the calibration scenario renders (fixtures/scenarios),
never on the held-out evaluation set.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple

import numpy as np
from PIL import Image
from scipy import ndimage

from submissions.kl2400033283.agent.schemas.evidence import ImageQuality

ANALYSIS_MAX_WIDTH = 1280

# Calibrated thresholds (see eval-report.md, "Quality gate calibration").
NATIVE_BLUR_MIN_SHARPNESS = 6.0  # same score on native-resolution tiles of large photos
BLUR_MIN_SHARPNESS = 8.0        # 99.9th pct |Laplacian| below this = blurred (blur ~3.6, sharp >= 12)
GLARE_MAX_PCT = 1.5              # % clipped pixels above this = glare risk
EXPOSURE_MIN_MEAN = 40.0         # mean luminance below this = under-exposed
EXPOSURE_MAX_MEAN = 225.0


@dataclass
class LoadedImage:
    path: Path
    rgb: np.ndarray          # H x W x 3 float32, 0-255 (analysis resolution)
    gray: np.ndarray         # H x W float32
    original_size: Tuple[int, int]
    scale: float             # analysis px / original px
    sha256: str
    native_sharpness: Optional[float] = None  # strongest-edge score on native-resolution tiles (big photos)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _edge_score(gray: np.ndarray) -> float:
    return float(np.percentile(np.abs(ndimage.laplace(ndimage.gaussian_filter(gray, 0.8))), 99.9))


def _native_sharpness(im: Image.Image, tile: int = 768) -> float:
    """Downscaling hides blur, so big photos are also scored at native resolution: the sharpest of
    a 3x3 grid of tiles (the sharpest tile, so a plain background in one tile does not count as blur)."""
    g = np.asarray(im.convert("L"), dtype=np.float32)
    h, w = g.shape
    best = 0.0
    for fy in (0.2, 0.5, 0.8):
        for fx in (0.2, 0.5, 0.8):
            cy, cx = int(h * fy), int(w * fx)
            patch = g[max(0, cy - tile // 2):cy + tile // 2, max(0, cx - tile // 2):cx + tile // 2]
            if patch.size:
                best = max(best, _edge_score(patch))
    return best


def load_image(path: Path) -> LoadedImage:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        scale = 1.0
        native = _native_sharpness(im) if w > ANALYSIS_MAX_WIDTH else None
        if w > ANALYSIS_MAX_WIDTH:
            scale = ANALYSIS_MAX_WIDTH / w
            im = im.resize((ANALYSIS_MAX_WIDTH, max(1, int(h * scale))), Image.BILINEAR)
        rgb = np.asarray(im, dtype=np.float32)
    gray = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    return LoadedImage(path, rgb, gray, (w, h), scale, sha256_file(path), native)


def assess_quality(img: LoadedImage) -> ImageQuality:
    # Strongest-edge response: content-independent, unlike Laplacian variance.
    lap = np.abs(ndimage.laplace(ndimage.gaussian_filter(img.gray, 0.8)))
    sharp = float(np.percentile(lap, 99.9))
    if img.native_sharpness is not None and img.native_sharpness < NATIVE_BLUR_MIN_SHARPNESS:
        sharp = min(sharp, img.native_sharpness)  # blurred at full resolution, whatever the thumbnail says
    clipped = float((img.rgb.min(axis=2) >= 253).mean() * 100.0)
    mean = float(img.gray.mean())
    issues: List[str] = []
    if sharp < BLUR_MIN_SHARPNESS:
        issues.append("BLUR")
    if clipped > GLARE_MAX_PCT:
        issues.append("GLARE")
    if mean < EXPOSURE_MIN_MEAN:
        issues.append("UNDEREXPOSED")
    if mean > EXPOSURE_MAX_MEAN:
        issues.append("OVEREXPOSED")
    # Glare alone does not make a frame unusable; it is handled per region.
    usable = not any(i in issues for i in ("BLUR", "UNDEREXPOSED", "OVEREXPOSED"))
    return ImageQuality(sharpness=round(sharp, 1), glare_pct=round(clipped, 2),
                        exposure_mean=round(mean, 1), usable=usable, issues=issues)
