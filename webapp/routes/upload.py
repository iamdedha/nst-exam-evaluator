"""File upload route."""
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash
from webapp.services import run_manager

upload_bp = Blueprint("upload", __name__)


@upload_bp.route("/upload", methods=["GET"])
def upload_form():
    return render_template("upload.html")


@upload_bp.route("/upload", methods=["POST"])
def handle_upload():
    part_a = request.files.get("part_a")
    part_b = request.files.get("part_b")

    if not part_a or not part_a.filename:
        flash("Please upload the Part A Excel file (.xlsx)", "error")
        return redirect(url_for("upload.upload_form"))

    if not part_b or not part_b.filename:
        flash("Please upload the Part B CSV file (.csv)", "error")
        return redirect(url_for("upload.upload_form"))

    if not part_a.filename.endswith(".xlsx"):
        flash("Part A file must be .xlsx format", "error")
        return redirect(url_for("upload.upload_form"))

    if not part_b.filename.endswith(".csv"):
        flash("Part B file must be .csv format", "error")
        return redirect(url_for("upload.upload_form"))

    # Create a new run
    run_id = run_manager.create_run(part_a.filename, part_b.filename)
    run_dir = run_manager.get_run_dir(run_id)
    uploads_dir = run_dir / "uploads"

    # Save uploaded files
    part_a.save(str(uploads_dir / "part_a.xlsx"))
    part_b.save(str(uploads_dir / "part_b.csv"))

    run_manager.update_meta(run_id, status="uploaded")
    flash(f"Files uploaded successfully! Run ID: {run_id}", "success")
    return redirect(url_for("evaluation.eval_page", run_id=run_id))
