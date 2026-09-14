import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
MEDIA_DIR = DATASET_DIR / "media" / "images"
OUTPUT_PATH = REPO_ROOT / "output.csv"
USAGE_REPORT_PATH = REPO_ROOT / "code" / "evaluation" / "usage_report.md"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
FORECAST_HORIZON_DAYS = 90
MAX_SPENDING_CHANGES = 3
MAX_OPTIMIZATION_ITERATIONS = 3
