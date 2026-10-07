"""API security controls.

* Authentication: ``X-API-Key`` maps to exactly one *principal* = (tenant, role, operator_id).
  The tenant, role and operator identity come from the credential, never from the request body
  or a client header, so a caller cannot claim another organisation or another person.
  Keys are compared as SHA-256 digests in constant time.
* Roles: ``operator`` (inspect, upload, tighten a verdict), ``supervisor`` (may also relax a
  verdict, e.g. FAIL->PASS), ``station`` (a fixed gantry camera: the only role whose uploads may be
  treated as calibrated station frames - and even then the frame must carry the reference card).
* Signed asset URLs: short-lived HMAC tokens bound to (org, asset, expiry).
* Uploads: size cap enforced *before* the body is read (Content-Length + streamed read), full
  decode, format allow-list, hard pixel cap (no 40-80 MP window), EXIF orientation applied and all
  metadata (EXIF/GPS) stripped by re-encoding; files stored under server-generated ids.
* Rate limiting per credential; security headers (CSP, frame denial, nosniff, referrer policy).
"""

import hashlib
import hmac
import io
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from fastapi import Header, HTTPException, Request
from PIL import Image, ImageOps

from submissions.kl2400033283.agent.config import (
    ALLOWED_IMAGE_FORMATS, ALLOWED_ORGS, API_KEYS_RAW, ASSET_URL_TTL_SECONDS, MAX_UPLOAD_BYTES,
    RATE_LIMIT_PER_MINUTE, SIGNING_SECRET,
)

MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS  # Pillow warns above this and errors at 2x; we reject explicitly below
ROLES = ("operator", "supervisor", "station")


@dataclass(frozen=True)
class Principal:
    org_id: str
    role: str
    operator_id: str

    @property
    def can_relax_verdicts(self) -> bool:
        return self.role == "supervisor"


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _parse_keys(raw: str) -> Dict[str, Principal]:
    """Format: ``org:key[:role[:operator_id]]`` comma-separated. Role defaults to operator."""
    table: Dict[str, Principal] = {}
    for item in raw.split(","):
        parts = [p.strip() for p in item.split(":")]
        if len(parts) < 2:
            continue
        org, key = parts[0], parts[1]
        role = parts[2] if len(parts) > 2 and parts[2] in ROLES else "operator"
        operator = parts[3] if len(parts) > 3 and parts[3] else f"{role}_{org.replace('org_demo_', '')}"
        if org in ALLOWED_ORGS and len(key) >= 8:
            table[_digest(key)] = Principal(org, role, operator)
    return table


_KEY_TABLE = _parse_keys(API_KEYS_RAW)


def resolve_principal(api_key: Optional[str]) -> Optional[Principal]:
    if not api_key:
        return None
    d = _digest(api_key)
    found = None
    for known, principal in _KEY_TABLE.items():
        if hmac.compare_digest(known, d):
            found = principal
    return found


def resolve_tenant(api_key: Optional[str]) -> Optional[str]:
    p = resolve_principal(api_key)
    return p.org_id if p else None


class RateLimiter:
    def __init__(self, per_minute: int):
        self.rate = per_minute / 60.0
        self.capacity = float(per_minute)
        self._buckets: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1, now)
            return True


limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)


def require_principal(request: Request, x_api_key: Optional[str] = Header(None)) -> Principal:
    """FastAPI dependency: authenticate and return the caller's principal."""
    p = resolve_principal(x_api_key)
    if p is None:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")
    if not limiter.allow(_digest(x_api_key)):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    request.state.org_id = p.org_id
    return p


def require_tenant(request: Request, x_api_key: Optional[str] = Header(None)) -> str:
    return require_principal(request, x_api_key).org_id


# ------------------------------------------------------------------ signed asset URLs
def sign_asset(org_id: str, asset_ref: str, ttl: int = ASSET_URL_TTL_SECONDS) -> Tuple[str, int]:
    exp = int(time.time()) + ttl
    msg = f"{org_id}|{asset_ref}|{exp}".encode("utf-8")
    return hmac.new(SIGNING_SECRET, msg, hashlib.sha256).hexdigest(), exp


def verify_asset_signature(org_id: str, asset_ref: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    msg = f"{org_id}|{asset_ref}|{exp}".encode("utf-8")
    expected = hmac.new(SIGNING_SECRET, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig or "")


# ------------------------------------------------------------------ uploads
_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


async def read_limited(upload, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    """Stream an UploadFile, aborting as soon as it exceeds ``limit`` (never buffers more)."""
    chunks, total = [], 0
    while True:
        chunk = await upload.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=f"Image larger than {limit // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass
class CleanImage:
    data: bytes            # re-encoded bytes actually stored (no metadata, orientation applied)
    sha256: str            # hash of the stored bytes
    original_sha256: str   # hash of what the client sent (kept for provenance)
    content_type: str
    ext: str
    width: int
    height: int


def validate_image_upload(data: bytes) -> CleanImage:
    """Validate, normalise orientation and strip metadata. Raises HTTPException(400/413)."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Image larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if len(data) < 100:
        raise HTTPException(status_code=400, detail="File too small to be an image")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            if im.width * im.height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=400, detail=f"Image has more than {MAX_IMAGE_PIXELS // 1_000_000} MP")
            im.verify()  # structural check
        with Image.open(io.BytesIO(data)) as im:
            im.load()    # full decode (verify() does not decode pixels)
            if im.width < 200 or im.height < 200:
                raise HTTPException(status_code=400, detail="Image resolution too low (min 200x200)")
            if fmt not in ALLOWED_IMAGE_FORMATS:
                raise HTTPException(status_code=400, detail=f"Format {fmt} not allowed (JPEG, PNG, WEBP)")
            im = ImageOps.exif_transpose(im)          # phones store rotation in EXIF
            im = im.convert("RGB")
            out = io.BytesIO()
            if fmt == "PNG":
                im.save(out, format="PNG", optimize=True)   # no metadata chunks written
            else:
                fmt = "JPEG"
                im.save(out, format="JPEG", quality=92)     # no exif= argument -> EXIF/GPS dropped
            cleaned = out.getvalue()
            w, h = im.size
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="File is not a decodable image")
    return CleanImage(cleaned, hashlib.sha256(cleaned).hexdigest(), hashlib.sha256(data).hexdigest(),
                      _MIME[fmt], _EXT[fmt], w, h)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; script-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}
