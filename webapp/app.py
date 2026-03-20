"""
NST Exam Evaluator - Web Application
Flask entry point with app factory.
"""
import sys
import os
from pathlib import Path
from flask import Flask

# Ensure evaluator is importable
EVALUATOR_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(EVALUATOR_DIR))
os.environ.setdefault("EVALUATOR_DIR", str(EVALUATOR_DIR))


def create_app():
    app = Flask(__name__,
                template_folder=str(Path(__file__).parent / "templates"),
                static_folder=str(Path(__file__).parent / "static"))

    app.config.from_object("webapp.config.Config")

    # Register blueprints
    from webapp.routes.main import main_bp
    from webapp.routes.upload import upload_bp
    from webapp.routes.evaluation import eval_bp
    from webapp.routes.results import results_bp
    from webapp.routes.export import export_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(eval_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(export_bp)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print("\n" + "=" * 50)
    print("  NST Exam Evaluator - Web Interface")
    print(f"  http://localhost:{port}")
    print("=" * 50 + "\n")
    app.run(debug=True, host="0.0.0.0", port=port, threaded=True)
