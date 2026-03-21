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
    """Start evaluation - runs synchronously via streaming response."""
    meta = run_manager.get_meta(run_id)
    if not meta:
        return jsonify({"error": "Run not found"}), 404

    if meta.get("status") in ("running", "complete"):
        return jsonify({"error": f"Evaluation already {meta['status']}"}), 409

    # Create progress tracker
    progress = create_progress(run_id)
    run_manager.update_meta(run_id, status="running")

    def _run_and_stream():
        """Run pipeline synchronously, yielding SSE events."""
        import traceback as tb_mod
        try:
            run_full_pipeline(run_id, progress)
        except BaseException as e:
            tb = tb_mod.format_exc()
            print(f"[PIPELINE ERROR] {e}\n{tb}", flush=True)
            try:
                progress.update(phase="error", error=str(e),
                               current_step=f"ERROR: {str(e)[:100]}")
                progress.log(f"ERROR: {tb}")
                run_manager.update_meta(run_id, status="error", phase="error",
                                       error=str(e), traceback=tb[-500:])
            except:
                pass

    # Run in a real OS thread using threading (not daemon)
    import threading
    t = threading.Thread(target=_run_and_stream, daemon=False)
    t.start()

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


@eval_bp.route("/eval/test-pipeline")
def test_pipeline():
    """Test that the pipeline can import and run Phase 0."""
    import sys, os, traceback
    results = {}
    eval_dir = str(run_manager.Config.EVALUATOR_DIR)
    if eval_dir not in sys.path:
        sys.path.insert(0, eval_dir)
    results["eval_dir"] = eval_dir
    results["eval_dir_exists"] = os.path.isdir(eval_dir)
    results["sys_path_0"] = sys.path[0]

    try:
        from phase0_data_cleanup import run_phase0_web
        results["import_phase0"] = "OK"
    except Exception as e:
        results["import_phase0"] = f"FAILED: {traceback.format_exc()[-300:]}"

    try:
        from webapp.services.pipeline import run_phase0, _setup_sys_path, _eval_lock
        results["import_pipeline"] = "OK"
        results["eval_lock_locked"] = _eval_lock.locked()
    except Exception as e:
        results["import_pipeline"] = f"FAILED: {traceback.format_exc()[-300:]}"

    try:
        import agents.part_a_evaluator
        results["import_part_a_eval"] = "OK"
    except Exception as e:
        results["import_part_a_eval"] = f"FAILED: {traceback.format_exc()[-300:]}"

    return jsonify(results)


@eval_bp.route("/eval/<run_id>/run-sync")
def run_sync(run_id):
    """Run pipeline synchronously and stream output as text for debugging."""
    import sys, traceback
    meta = run_manager.get_meta(run_id)
    if not meta:
        return "Run not found", 404

    def generate():
        eval_dir = str(run_manager.Config.EVALUATOR_DIR)
        if eval_dir not in sys.path:
            sys.path.insert(0, eval_dir)

        yield "=== SYNC PIPELINE START ===\n"

        run_dir = run_manager.get_run_dir(run_id)
        output_dir = run_dir / "output"
        uploads_dir = run_dir / "uploads"

        yield f"Run dir: {run_dir}\n"
        yield f"Uploads: {list(uploads_dir.iterdir()) if uploads_dir.exists() else 'MISSING'}\n"

        xlsx_path = uploads_dir / "part_a.xlsx"
        csv_path = uploads_dir / "part_b.csv"
        yield f"Part A exists: {xlsx_path.exists()}\n"
        yield f"Part B exists: {csv_path.exists()}\n"

        # Phase 0
        try:
            yield "\n=== PHASE 0 ===\n"
            from phase0_data_cleanup import run_phase0_web
            summary = run_phase0_web(str(xlsx_path), str(csv_path), output_dir)
            valid = summary['stats']['total_valid_part_a']
            yield f"Phase 0 OK: {valid} valid students\n"

            for s in summary.get('valid_students', [])[:5]:
                yield f"  Student: {s['roll_number']} - {s['full_name']}\n"

        except Exception as e:
            yield f"Phase 0 FAILED:\n{traceback.format_exc()}\n"
            return

        # Part A (just first student as test)
        try:
            yield "\n=== PART A (first student only) ===\n"
            import agents.part_a_evaluator as pa_eval
            student = summary['valid_students'][0]
            yield f"Evaluating: {student['roll_number']} ({student['full_name']})\n"
            result = pa_eval.evaluate_student_part_a(student, 0)
            yield f"Score: {result.get('final_total', '?')}/50\n"
            yield f"Flags: {result.get('flags', [])}\n"
        except Exception as e:
            yield f"Part A FAILED:\n{traceback.format_exc()}\n"

        yield "\n=== DONE ===\n"

    return Response(generate(), mimetype='text/plain',
                   headers={"X-Accel-Buffering": "no"})


@eval_bp.route("/eval/<run_id>/status")
def eval_status(run_id):
    """JSON status endpoint."""
    progress = get_progress(run_id)
    if progress:
        return jsonify(progress.to_dict())

    meta = run_manager.get_meta(run_id)
    return jsonify(meta or {"error": "Run not found"})
