"""Web app configuration."""
import os
from pathlib import Path

EVALUATOR_DIR = Path(__file__).parent.parent
WEBAPP_DIR = Path(__file__).parent

class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "nst-exam-evaluator-2026")
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB max upload
    RUNS_DIR = WEBAPP_DIR / "runs"
    EVALUATOR_DIR = EVALUATOR_DIR
    OUTPUT_DIR = EVALUATOR_DIR / "output"
    GROUND_TRUTH_DIR = EVALUATOR_DIR / "output" / "ground_truths"
    UPLOAD_EXTENSIONS = {".xlsx", ".csv"}
