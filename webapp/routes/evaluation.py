"""Evaluation routes: start, progress SSE, status."""
import threading
from flask import Blueprint, render_template, jsonify, Response, stream_with_context, redirect, url_for
from webapp.services import run_manager
from webapp.services.progress import create_progress, get_progress
from webapp.services.pipeline import run_full_pipeline

eval_bp = Blueprint("evaluation", __name__)


@eval_bp.route("/eval/<run_id>")
def eval_page(run_id):
    meta = run_manager.get_meta(run_id)
    if not meta:
        return "Run not found", 404
    progress = get_progress(run_id)
    return render_template("running.html", run_id=run_id, meta=meta,
                         progress=progress)


@eval_bp.route("/eval/<run_id>/start", methods=["POST"])
def start_eval(run_id):
    meta = run_manager.get_meta(run_id)
    if not meta:
        return jsonify({"error": "Run not found"}), 404

    if meta.get("status") == "running":
        return jsonify({"error": "Evaluation already running"}), 409

    # Create progress tracker
    progress = create_progress(run_id)

    # Start evaluation in background thread
    thread = threading.Thread(
        target=run_full_pipeline,
        args=(run_id, progress),
        daemon=True,
        name=f"eval-{run_id}",
    )
    thread.start()

    run_manager.update_meta(run_id, status="running")
    return jsonify({"status": "started", "run_id": run_id})


@eval_bp.route("/eval/<run_id>/progress")
def progress_stream(run_id):
    """SSE endpoint for real-time progress updates."""
    progress = get_progress(run_id)
    if not progress:
        # Check if run is already complete
        meta = run_manager.get_meta(run_id)
        if meta and meta.get("status") == "complete":
            def done():
                yield 'data: {"type": "progress", "phase": "complete"}\n\n'
            return Response(done(), mimetype="text/event-stream")
        return Response('data: {"error": "No active evaluation"}\n\n',
                       mimetype="text/event-stream")

    return Response(
        stream_with_context(progress.get_events(timeout=30)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


@eval_bp.route("/eval/<run_id>/status")
def eval_status(run_id):
    """JSON status endpoint."""
    progress = get_progress(run_id)
    if progress:
        return jsonify(progress.to_dict())

    meta = run_manager.get_meta(run_id)
    return jsonify(meta or {"error": "Run not found"})
