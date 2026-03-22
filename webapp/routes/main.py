"""Dashboard route with chart data."""
import os
from flask import Blueprint, render_template, jsonify
from webapp.services import run_manager

main_bp = Blueprint("main", __name__)


def _build_chart_data(scores, phase0_students=None):
    """Build Plotly-ready chart data from master scores and phase0 student data."""
    part_a_scores = []
    methods = {}
    scatter_x, scatter_y, scatter_labels = [], [], []

    # Build method lookup from phase0 data
    method_by_roll = {}
    if phase0_students:
        for s in phase0_students:
            roll = s.get("roll_number", "")
            method = s.get("primary_method", "")
            if method:
                # Normalize: "Support Vector Machine (SVM)" -> "SVM"
                if "svm" in method.lower() or "support vector" in method.lower():
                    method_by_roll[roll] = "SVM"
                elif "gmm" in method.lower() or "gaussian mixture" in method.lower():
                    method_by_roll[roll] = "GMM"
                elif "arima" in method.lower() or "time series" in method.lower():
                    method_by_roll[roll] = "Time Series"
                else:
                    method_by_roll[roll] = method.split(",")[0].strip()

    for s in scores:
        a = s.get("Part A Final (50)", 0)
        if isinstance(a, (int, float)) and a > 0:
            part_a_scores.append(a)

        # Method breakdown from phase0 lookup
        roll = s.get("Roll Number", "")
        method = method_by_roll.get(roll, "")
        if method:
            methods[method] = methods.get(method, 0) + 1

        # Scatter: A vs B
        b_raw = s.get("Part B Raw (130)", "NO SUBMISSION")
        if isinstance(a, (int, float)) and isinstance(b_raw, (int, float)):
            scatter_x.append(a)
            scatter_y.append(s.get("Part B Final (130)", 0))
            scatter_labels.append(f"{roll} {s.get('Name', '')}")

    return {
        "part_a_scores": part_a_scores,
        "methods": methods,
        "scatter": {"x": scatter_x, "y": scatter_y, "labels": scatter_labels},
    }


@main_bp.route("/")
def index():
    runs = run_manager.list_runs()

    # Get stats and chart data from the latest completed run
    stats = {"total": 0, "avg_a": 0, "part_b": 0, "flagged": 0}
    chart_data = None

    latest = next((r for r in runs if r.get("has_results")), None)
    if latest:
        data = run_manager.get_results_data(latest["run_id"])
        scores = data.get("master_scores", [])
        if scores:
            valid = [s for s in scores if s.get("Status") == "valid"]
            a_scores = [s.get("Part A Final (50)", 0) for s in valid
                        if isinstance(s.get("Part A Final (50)"), (int, float))]
            b_count = sum(1 for s in valid
                          if s.get("Part B Raw (130)") not in ["NO SUBMISSION", "N/A", "N/A (disqualified)"]
                          and isinstance(s.get("Part B Raw (130)"), (int, float)))

            stats = {
                "total": len(scores),
                "avg_a": round(sum(a_scores) / max(len(a_scores), 1), 1),
                "part_b": b_count,
                "flagged": sum(1 for s in scores if s.get("Needs Review") == "YES"),
            }
            phase0 = data.get("phase0", {})
            phase0_students = phase0.get("valid_students", [])
            chart_data = _build_chart_data(scores, phase0_students)

    return render_template("index.html", runs=runs, stats=stats, chart_data=chart_data)


@main_bp.route("/health")
def health():
    """Debug endpoint to check environment and imports."""
    checks = {"version": "v25-split-part-b"}
    # Check env vars
    checks["GEMINI_API_KEY"] = "set" if os.environ.get("GEMINI_API_KEY") else "NOT SET"
    checks["OPENROUTER_API_KEY"] = "set" if os.environ.get("OPENROUTER_API_KEY") else "NOT SET"
    checks["GITHUB_TOKEN"] = "set" if os.environ.get("GITHUB_TOKEN") else "NOT SET"
    checks["LLM_PROVIDER"] = os.environ.get("LLM_PROVIDER", "not set (default)")

    # Check imports
    for mod in ["flask", "requests", "openpyxl", "numpy", "bs4", "google.generativeai", "pypdf"]:
        try:
            __import__(mod)
            checks[f"import_{mod}"] = "OK"
        except ImportError as e:
            checks[f"import_{mod}"] = f"FAILED: {e}"

    # Check evaluator imports
    import sys
    from pathlib import Path
    eval_dir = str(Path(__file__).parent.parent.parent)
    if eval_dir not in sys.path:
        sys.path.insert(0, eval_dir)
    for mod in ["phase0_data_cleanup", "agents.llm_client", "agents.part_a_evaluator", "agents.github_checker"]:
        try:
            __import__(mod)
            checks[f"import_{mod}"] = "OK"
        except Exception as e:
            checks[f"import_{mod}"] = f"FAILED: {e}"

    return jsonify(checks)
