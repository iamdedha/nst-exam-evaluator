"""Root entry point for Render/gunicorn deployment."""
import sys
import os
from pathlib import Path

# Ensure project root is on the path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("EVALUATOR_DIR", str(ROOT))

from webapp.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
