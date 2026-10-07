"""Runtime configuration for the Prep Manager agent.

Every tunable comes from the environment so the same build runs in dev, CI and
a prep-station deployment. Nothing secret is hard-coded: when a secret is not
supplied we generate an ephemeral one and say so loudly at startup.
"""

import hashlib
import os
import secrets
from pathlib import Path

AGENT_VERSION = "2.0.0"
SCHEMA_VERSION = "2026.2"
RULES_VERSION = "fba-prep-rules-2026.10"

# ---------------------------------------------------------------- paths
SUBMISSION_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SUBMISSION_DIR.parent.parent
DATA_DIR = Path(os.environ.get("PREP_DATA_DIR", SUBMISSION_DIR / "data_store"))
FIXTURES_DIR = SUBMISSION_DIR / "fixtures"
SCENARIO_DIR = FIXTURES_DIR / "scenarios"
UPLOAD_DIR = DATA_DIR / "uploads"
EVAL_RESULTS_PATH = SUBMISSION_DIR / "eval" / "eval_results.json"

for _d in (DATA_DIR, FIXTURES_DIR, SCENARIO_DIR, UPLOAD_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("PREP_DB_PATH", DATA_DIR / "prep_manager_v2.db"))

# ---------------------------------------------------------------- tenancy & auth
ALLOWED_ORGS = ["org_demo_alpha", "org_demo_bravo"]

# Format: "org:key[:role[:operator_id]]" comma-separated; role is operator | supervisor | station.
# The credential decides tenant, role and operator identity. Demo keys are only for local
# evaluation; DEMO_KEYS_ACTIVE lets the API warn about it.
_DEFAULT_DEMO_KEYS = (
    "org_demo_alpha:alpha-demo-key:operator:op_alpha,"
    "org_demo_alpha:alpha-supervisor-key:supervisor:sup_alpha,"
    "org_demo_alpha:alpha-station-key:station:station_alpha_01,"
    "org_demo_bravo:bravo-demo-key:operator:op_bravo,"
    "org_demo_bravo:bravo-supervisor-key:supervisor:sup_bravo"
)
API_KEYS_RAW = os.environ.get("PREP_API_KEYS", _DEFAULT_DEMO_KEYS)
DEMO_KEYS_ACTIVE = "PREP_API_KEYS" not in os.environ

_signing = os.environ.get("PREP_SIGNING_SECRET")
SIGNING_SECRET_EPHEMERAL = _signing is None
SIGNING_SECRET = (_signing or secrets.token_hex(32)).encode("utf-8")
ASSET_URL_TTL_SECONDS = int(os.environ.get("PREP_ASSET_URL_TTL", "900"))

# Evidence seal key (HMAC-SHA256). Held OUTSIDE the database: from PREP_SEAL_KEY, else a key file
# created once in a separate directory. Anyone who can edit the DB but not read this key cannot
# forge a seal. Production: load from a KMS/HSM instead of a file.
SEAL_KEY_DIR = Path(os.environ.get("PREP_SEAL_KEY_DIR", SUBMISSION_DIR / "data_store" / "keys"))


def _load_seal_key() -> bytes:
    env = os.environ.get("PREP_SEAL_KEY")
    if env:
        return env.encode("utf-8")
    SEAL_KEY_DIR.mkdir(parents=True, exist_ok=True)
    f = SEAL_KEY_DIR / "seal.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32), encoding="ascii")
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    return f.read_text(encoding="ascii").strip().encode("utf-8")


SEAL_KEY = _load_seal_key()
SEAL_KEY_ID = hashlib.sha256(SEAL_KEY).hexdigest()[:12]  # identifies the key without revealing it

CORS_ORIGINS = [o for o in os.environ.get("PREP_CORS_ORIGINS", "").split(",") if o]
RATE_LIMIT_PER_MINUTE = int(os.environ.get("PREP_RATE_LIMIT_PER_MIN", "240"))

# ---------------------------------------------------------------- uploads
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGES_PER_UNIT = 4
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}

# ---------------------------------------------------------------- perception
# "auto": calibrated station frames -> station CV; real photos -> Claude/LLM vision when available,
# otherwise the offline local OCR engine. "cv" / "claude" / "ollama" / "ocr" force one.
PERCEPTION_MODE = os.environ.get("PREP_PERCEPTION", "auto").lower()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("PREP_OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("PREP_OLLAMA_MODEL", "llava:latest")
OLLAMA_TIMEOUT_MS = int(os.environ.get("PREP_OLLAMA_TIMEOUT_MS", "120000"))
# FREE-ONLY LOCK: paid model APIs are never called unless this is explicitly set to "1",
# even if an API key happens to be present in the environment.
ALLOW_PAID_MODELS = os.environ.get("PREP_ALLOW_PAID_MODELS", "0") == "1"

# Free cloud vision (OpenAI-compatible; OpenRouter ':free' models). Key comes from the environment only.
FREE_VISION_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
# Tried in order; a model that is rate-limited or withdrawn is skipped. Every id must end in ":free".
FREE_VISION_MODELS = [m.strip() for m in os.environ.get(
    "PREP_FREE_VISION_MODELS",
    "google/gemma-4-31b-it:free,google/gemma-4-26b-a4b-it:free,nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
).split(",") if m.strip()]
FREE_VISION_MODEL = FREE_VISION_MODELS[0]
FREE_VISION_URL = os.environ.get("PREP_FREE_VISION_URL", "https://openrouter.ai/api/v1/chat/completions")
FREE_VISION_MAX_EDGE = 1024
FREE_VISION_TIMEOUT_MS = int(os.environ.get("PREP_FREE_VISION_TIMEOUT_MS", "120000"))
CLAUDE_MODEL = os.environ.get("PREP_CLAUDE_MODEL", "claude-haiku-4-5-20251001")
CLAUDE_API_URL = os.environ.get("PREP_CLAUDE_API_URL", "https://api.anthropic.com/v1/messages")
CLAUDE_MAX_IMAGE_EDGE = 1568
# USD per million tokens for cost accounting (Haiku 4.5 list price).
CLAUDE_PRICE_IN_PER_MTOK = float(os.environ.get("PREP_PRICE_IN", "1.0"))
CLAUDE_PRICE_OUT_PER_MTOK = float(os.environ.get("PREP_PRICE_OUT", "5.0"))

CV_ENGINE_VERSION = "station-cv-1.0"

# Station optics calibration: the fixed gantry images an area of 16 x 12 in
# onto a 1280 x 960 frame, i.e. 80 px per inch. Used for font-size and gap
# measurements. A deployment re-calibrates this with a printed target.
STATION_PX_PER_INCH = float(os.environ.get("PREP_PX_PER_INCH", "80"))

# ---------------------------------------------------------------- budgets
# Raised from 1.5 s: station CV measured 0.5-1.1 s on a laptop, so 1.5 s left too little headroom.
PERCEPTION_TIMEOUT_MS = int(os.environ.get("PREP_PERCEPTION_TIMEOUT_MS", "5000"))
# Local OCR is slower (CPU text detection per view); it serves manual real-photo inspections, not the gantry.
OCR_TIMEOUT_MS = int(os.environ.get("PREP_OCR_TIMEOUT_MS", "30000"))
MAX_MODEL_CALLS_PER_UNIT = 1
UNIT_COST_CEILING_USD = 0.02  # Kill condition 3

# Kill conditions
KC1_MAX_BARCODE_FN_RATE = 0.015
KC2_MAX_TENANT_LEAKAGE_ROWS = 0
KC3_MAX_UNIT_COST_USD = UNIT_COST_CEILING_USD
