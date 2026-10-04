"""System configuration and constants for Prep Manager Agent."""

import os
from pathlib import Path

# Base Paths
SUBMISSION_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SUBMISSION_DIR.parent.parent
DATA_DIR = SUBMISSION_DIR / "data_store"
FIXTURES_DIR = SUBMISSION_DIR / "fixtures"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

# Database
DB_PATH = DATA_DIR / "prep_manager_tenancy.db"

# Multitenancy
ALLOWED_ORGS = ["org_demo_alpha", "org_demo_bravo"]

# Operational Latency & Circuit Breaker Limits
MAX_VISION_LATENCY_MS = 1500  # Fail-open threshold
CIRCUIT_BREAKER_FAIL_OPEN_STATUS = "pending"
DEFAULT_MODEL_VERSION = "prep-vision-hybrid-v2.6"

# Kill Condition Thresholds
KC1_MAX_BARCODE_FN_RATE = 0.015  # 1.5% max false negative on uncovered barcodes
KC2_MAX_TENANT_LEAKAGE_ROWS = 0  # Zero rows tolerated across tenant boundary
KC3_MAX_UNIT_COST_USD = 0.02     # $0.02 max cost per evaluated unit
KC4_MAX_BLOCKING_DOWNTIME_MS = 2000

# Cost Accounting
MOCK_INFERENCE_COST_USD = 0.0028  # Batched multimodal cost per unit
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
