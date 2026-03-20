"""Export routes: CSV, JSON, report download."""
from flask import Blueprint, send_file, abort
from webapp.services import run_manager

export_bp = Blueprint("export", __name__)


@export_bp.route("/export/<run_id>/csv")
def download_csv(run_id):
    output_dir = run_manager.get_run_output_dir(run_id)
    csv_path = output_dir / "master_scores.csv"
    if not csv_path.exists():
        abort(404, "Scores CSV not generated yet")
    return send_file(str(csv_path), mimetype="text/csv",
                    as_attachment=True,
                    download_name=f"evaluation_scores_{run_id}.csv")


@export_bp.route("/export/<run_id>/json")
def download_json(run_id):
    output_dir = run_manager.get_run_output_dir(run_id)
    json_path = output_dir / "master_scores.json"
    if not json_path.exists():
        abort(404, "Scores JSON not generated yet")
    return send_file(str(json_path), mimetype="application/json",
                    as_attachment=True,
                    download_name=f"evaluation_scores_{run_id}.json")


@export_bp.route("/export/<run_id>/report")
def download_report(run_id):
    output_dir = run_manager.get_run_output_dir(run_id)
    report_path = output_dir / "detailed_report.txt"
    if not report_path.exists():
        abort(404, "Detailed report not generated yet")
    return send_file(str(report_path), mimetype="text/plain",
                    as_attachment=True,
                    download_name=f"detailed_report_{run_id}.txt")


@export_bp.route("/export/<run_id>/student/<roll>")
def download_student_json(run_id, roll):
    output_dir = run_manager.get_run_output_dir(run_id)
    # Try Part A
    pa_path = output_dir / "part_a_scores" / f"{roll}_part_a.json"
    pb_path = output_dir / "part_b_scores" / f"{roll}_part_b.json"

    import json
    combined = {}
    if pa_path.exists():
        with open(pa_path) as f:
            combined["part_a"] = json.load(f)
    if pb_path.exists():
        with open(pb_path) as f:
            combined["part_b"] = json.load(f)

    if not combined:
        abort(404, "Student data not found")

    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(combined, tmp, indent=2, default=str)
    tmp.close()
    return send_file(tmp.name, mimetype="application/json",
                    as_attachment=True,
                    download_name=f"student_{roll}_{run_id}.json")
