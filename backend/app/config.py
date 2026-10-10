"""Environment + thresholds. Single source of truth for paths and modes."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]          # PillSpark/
BACKEND = ROOT / "backend"
DATA_DIR = ROOT / "data"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
REAL_DIR = DATA_DIR / "real_samples"
PHOTO_DIR = DATA_DIR / "user_photos"
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = DATA_DIR / ".cache"
for d in (SYNTHETIC_DIR, REAL_DIR, PHOTO_DIR, OUTPUT_DIR, CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT / ".env")
load_dotenv(BACKEND / ".env")


def _clean(v: str) -> str:
    v = (v or "").strip()
    # ignore placeholders copied from .env.example
    if not v or v.endswith("...") or v.startswith("00000000-0000"):
        return ""
    return v


# accept a few aliases so a hand-written .env still works (user wrote API_PillSpark=...)
NICRRON_API_KEY = next((_clean(os.getenv(k, "")) for k in ("NICRRON_API_KEY", "API_PillSpark", "API_PILLSPARK", "NICRRON_KEY") if _clean(os.getenv(k, ""))), "")
NICRRON_BASE_URL = os.getenv("NICRRON_BASE_URL", "https://api.nicrron.ai/v1").rstrip("/")
MODEL_PRIMARY = os.getenv("PILLSPARK_MODEL_PRIMARY", "anthropic/claude-sonnet-5")
MODEL_SECOND = os.getenv("PILLSPARK_MODEL_SECOND", "openai/gpt-5.4-mini")
PASSES = max(1, int(os.getenv("PILLSPARK_PASSES", "3")))

_requested_mode = os.getenv("LLM_MODE", "live").strip().lower()
LLM_MODE = "live" if (_requested_mode == "live" and NICRRON_API_KEY) else "mock"
LLM_MODE_REASON = (
    "live: NICRRON_API_KEY present" if LLM_MODE == "live"
    else ("mock: LLM_MODE=mock requested" if _requested_mode == "mock" else "mock: NICRRON_API_KEY missing")
)

PRISM_HOST = os.getenv("PRISMTRACE_HOST", "https://prism.blockconvey.com").rstrip("/")
PRISM_PROJECT_ID = _clean(os.getenv("PRISMTRACE_PROJECT_ID", ""))
PRISM_API_KEY = _clean(os.getenv("PRISMTRACE_API_KEY", ""))
PRISM_ENABLED = bool(PRISM_PROJECT_ID and PRISM_API_KEY)

VERIFIED_MIN = float(os.getenv("PILLSPARK_VERIFIED_MIN", "0.90"))
REVIEW_MIN = float(os.getenv("PILLSPARK_REVIEW_MIN", "0.70"))

# Field order is the order the pharmacist sees them.
FIELDS = [
    "patient_name", "patient_dob",
    "drug_name", "strength", "dosage_form", "quantity", "sig", "refills",
    "prescriber_name", "prescriber_npi", "prescriber_dea", "date_written",
]
REQUIRED_FIELDS = ["patient_name", "patient_dob", "drug_name", "strength", "quantity", "sig", "prescriber_name", "date_written"]
