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


@eval_bp.route("/eval/<run_id>/start", methods=["POST", "GET"])
def start_eval(run_id):
    """Mark run as started. Frontend then calls /run-step repeatedly."""
    meta = run_manager.get_meta(run_id)
    if not meta:
        return jsonify({"error": "Run not found"}), 404
    if meta.get("status") == "complete":
        return jsonify({"error": "Evaluation already complete"}), 409
    run_manager.update_meta(run_id, status="running", phase="started")
    create_progress(run_id)
    return jsonify({"status": "started", "run_id": run_id})


@eval_bp.route("/eval/<run_id>/run-step")
def run_step(run_id):
    """Run one step of the pipeline. Frontend calls this repeatedly until complete.
    Each call does one unit of work (Phase 0, or 1 student, or aggregation) and returns."""
    import sys, traceback, gc
    meta = run_manager.get_meta(run_id)
    if not meta:
        return jsonify({"error": "Run not found"}), 404

    eval_dir = str(run_manager.Config.EVALUATOR_DIR)
    if eval_dir not in sys.path:
        sys.path.insert(0, eval_dir)

    phase = meta.get("phase", "started")
    run_dir = run_manager.get_run_dir(run_id)
    output_dir = run_dir / "output"
    uploads_dir = run_dir / "uploads"

    try:
        if phase in ("started", "running"):
            # Phase 0
            run_manager.update_meta(run_id, phase="phase0", current_step="Running Phase 0...")
            from phase0_data_cleanup import run_phase0_web
            summary = run_phase0_web(str(uploads_dir / "part_a.xlsx"), str(uploads_dir / "part_b.csv"), output_dir)
            valid_count = summary["stats"]["total_valid_part_a"]
            run_manager.update_meta(run_id, phase="phase0_done", total_students=valid_count,
                                   current_step=f"Phase 0 complete: {valid_count} students", evaluated_part_a=0)
            return jsonify({"step": "phase0", "result": f"{valid_count} valid students", "next": "part_a"})

        elif phase in ("phase0_done", "part_a"):
            # Evaluate next student
            import agents.part_a_evaluator as pa_eval
            import json as _json

            # Load summary
            with open(output_dir / "phase0_summary.json") as f:
                summary = _json.load(f)

            scores_dir = output_dir / "part_a_scores"
            scores_dir.mkdir(parents=True, exist_ok=True)
            gt_dir = output_dir / "ground_truths"
            gt_dir.mkdir(parents=True, exist_ok=True)
            pa_eval.OUTPUT_DIR = output_dir
            pa_eval.SCORES_DIR = scores_dir
            pa_eval.GROUND_TRUTH_DIR = gt_dir

            valid_students = summary.get("valid_students", [])
            evaluated = meta.get("evaluated_part_a", 0)

            if evaluated < len(valid_students):
                student = valid_students[evaluated]
                roll = student["roll_number"]
                name = student["full_name"]
                penalties = summary.get("resubmission_penalties", {})
                penalty_pct = penalties.get(roll, {}).get("penalty_percentage", 0)

                run_manager.update_meta(run_id, phase="part_a",
                    current_step=f"Evaluating {roll} ({name}) [{evaluated+1}/{len(valid_students)}]",
                    current_index=evaluated+1)

                try:
                    result = pa_eval.evaluate_student_part_a(student, penalty_pct)
                    score = result.get("final_total", 0)
                    flags = result.get("flags", [])

                    # Save individual result
                    slim = {"roll_number": roll, "full_name": name, "final_total": score,
                            "raw_total": result.get("raw_total", 0), "scaled_score": result.get("scaled_score", 0),
                            "flags": flags}

                    # Append to all results
                    results_path = output_dir / "part_a_all_results.json"
                    existing = []
                    if results_path.exists():
                        with open(results_path) as f:
                            existing = _json.load(f)
                    existing.append(slim)
                    with open(results_path, "w") as f:
                        _json.dump(existing, f, indent=2, default=str)

                    run_manager.update_meta(run_id, evaluated_part_a=evaluated+1,
                        current_step=f"{roll}: {score}/50")
                    gc.collect()
                    return jsonify({"step": "part_a", "student": roll, "score": score,
                                   "progress": f"{evaluated+1}/{len(valid_students)}", "next": "part_a"})
                except Exception as e:
                    run_manager.update_meta(run_id, evaluated_part_a=evaluated+1,
                        current_step=f"{roll}: ERROR - {str(e)[:50]}")
                    # Save error result
                    results_path = output_dir / "part_a_all_results.json"
                    existing = []
                    if results_path.exists():
                        with open(results_path) as f:
                            existing = _json.load(f)
                    existing.append({"roll_number": roll, "error": str(e), "final_total": 0,
                                    "raw_total": 0, "scaled_score": 0, "flags": ["EVALUATION_ERROR"]})
                    with open(results_path, "w") as f:
                        _json.dump(existing, f, indent=2, default=str)
                    gc.collect()
                    return jsonify({"step": "part_a", "student": roll, "error": str(e),
                                   "progress": f"{evaluated+1}/{len(valid_students)}", "next": "part_a"})
            else:
                # All Part A students done — check if Part B needed
                with open(output_dir / "phase0_summary.json") as f2:
                    summ = _json.load(f2)
                has_part_b = summ["stats"]["total_part_b_submissions"] > 0
                has_part_c = (uploads_dir / "part_c.xlsx").exists()
                next_phase = "part_b" if has_part_b else ("part_c" if has_part_c else "aggregate")
                run_manager.update_meta(run_id, phase="part_a_done",
                    current_step=f"Part A complete: {evaluated}/{len(valid_students)}", evaluated_part_b=0)
                return jsonify({"step": "part_a_done", "next": next_phase})

        elif phase in ("part_a_done", "part_b"):
            # Part B: evaluate one student per call
            import json as _json
            from agents.github_checker import parse_github_url, check_repo_exists
            from agents.paper_ground_truth import generate_ground_truth
            import agents.part_b_evaluator as pb_eval

            with open(output_dir / "phase0_summary.json") as f:
                summary = _json.load(f)

            pb_eval.OUTPUT_DIR = output_dir
            scores_dir = output_dir / "part_b_scores"
            scores_dir.mkdir(parents=True, exist_ok=True)
            pb_eval.SCORES_DIR = scores_dir

            part_b_students = summary.get("part_b_students", [])
            valid_a = {s["roll_number"]: s for s in summary.get("valid_students", [])}
            by_roll = {}
            for s in part_b_students:
                by_roll[s["roll_number"]] = s
            b_list = list(by_roll.items())

            evaluated_b = meta.get("evaluated_part_b", 0)
            if evaluated_b < len(b_list):
                roll, student_b = b_list[evaluated_b]
                student_a = valid_a.get(roll, {})
                run_manager.update_meta(run_id, phase="part_b",
                    current_step=f"Part B: {roll} ({student_b['full_name']}) [{evaluated_b+1}/{len(b_list)}]")

                if not student_a:
                    run_manager.update_meta(run_id, evaluated_part_b=evaluated_b+1)
                    return jsonify({"step": "part_b", "student": roll, "error": "No valid Part A", "next": "part_b"})

                # Load/generate ground truth
                gt_dir = output_dir / "ground_truths"
                gt_dir.mkdir(parents=True, exist_ok=True)
                safe_title = student_a["paper_title"][:60].replace("/", "_").replace(" ", "_")
                gt_path = gt_dir / f"{safe_title}.json"
                if gt_path.exists():
                    with open(gt_path) as f:
                        ground_truth = _json.load(f)
                else:
                    ground_truth = generate_ground_truth(
                        title=student_a["paper_title"], venue=student_a["venue"],
                        year=student_a.get("year_of_publication", 0),
                        method=student_a["primary_method"],
                        url=student_a.get("paper_link", ""))
                    if ground_truth:
                        with open(gt_path, "w") as f:
                            _json.dump(ground_truth, f, indent=2)

                try:
                    result = pb_eval.evaluate_student_part_b(student_b, student_a, ground_truth or {})
                    score = result.get("final_total", 0)
                    # Save
                    results_path = output_dir / "part_b_all_results.json"
                    existing = []
                    if results_path.exists():
                        with open(results_path) as f:
                            existing = _json.load(f)
                    existing.append({"roll_number": roll, "final_total": score,
                                    "raw_total": result.get("raw_total", 0),
                                    "scaled_score": result.get("scaled_score", 0),
                                    "flags": result.get("flags", [])})
                    with open(results_path, "w") as f:
                        _json.dump(existing, f, indent=2, default=str)
                    run_manager.update_meta(run_id, evaluated_part_b=evaluated_b+1)
                    gc.collect()
                    return jsonify({"step": "part_b", "student": roll, "score": score,
                                   "progress": f"{evaluated_b+1}/{len(b_list)}", "next": "part_b"})
                except Exception as e:
                    results_path = output_dir / "part_b_all_results.json"
                    existing = []
                    if results_path.exists():
                        with open(results_path) as f:
                            existing = _json.load(f)
                    existing.append({"roll_number": roll, "error": str(e), "final_total": 0, "flags": ["EVALUATION_ERROR"]})
                    with open(results_path, "w") as f:
                        _json.dump(existing, f, indent=2, default=str)
                    run_manager.update_meta(run_id, evaluated_part_b=evaluated_b+1)
                    gc.collect()
                    return jsonify({"step": "part_b", "student": roll, "error": str(e), "next": "part_b"})
            else:
                has_part_c = (uploads_dir / "part_c.xlsx").exists()
                next_phase = "part_c" if has_part_c else "aggregate"
                run_manager.update_meta(run_id, phase="part_b_done",
                    current_step=f"Part B complete: {evaluated_b}/{len(b_list)}", evaluated_part_c=0)
                return jsonify({"step": "part_b_done", "next": next_phase})

        elif phase in ("part_b_done", "part_c"):
            # Part C: evaluate all at once (cross-verification)
            import json as _json
            run_manager.update_meta(run_id, phase="part_c", current_step="Running Part C cross-verification...")
            with open(output_dir / "phase0_summary.json") as f:
                summary = _json.load(f)
            try:
                from agents.part_c_evaluator import run_part_c_evaluation
                pc_results = run_part_c_evaluation(
                    str(uploads_dir / "part_c.xlsx"),
                    summary.get("valid_students", []),
                    output_dir)
                evaluated_c = sum(1 for r in pc_results if "error" not in r)
                run_manager.update_meta(run_id, phase="part_c_done", evaluated_part_c=evaluated_c,
                    current_step=f"Part C complete: {evaluated_c} verified")
                return jsonify({"step": "part_c_done", "evaluated": evaluated_c, "next": "aggregate"})
            except Exception as e:
                run_manager.update_meta(run_id, phase="part_c_done", current_step=f"Part C error: {str(e)[:50]}")
                return jsonify({"step": "part_c_error", "error": str(e), "next": "aggregate"})

        elif phase in ("part_c_done", "aggregate"):
            # Aggregation — combine Part A + B + C
            import json as _json, csv as csv_mod
            run_manager.update_meta(run_id, phase="aggregate", current_step="Aggregating scores...")

            with open(output_dir / "phase0_summary.json") as f:
                summary = _json.load(f)

            # Load all results
            pa_by_roll, pb_by_roll, pc_by_roll = {}, {}, {}
            for path, target in [
                (output_dir / "part_a_all_results.json", pa_by_roll),
                (output_dir / "part_b_all_results.json", pb_by_roll),
                (output_dir / "part_c_all_results.json", pc_by_roll),
            ]:
                if path.exists():
                    with open(path) as f:
                        for r in _json.load(f):
                            target[r["roll_number"]] = r

            rows = []
            for s in summary.get("valid_students", []):
                roll = s["roll_number"]
                pa = pa_by_roll.get(roll, {})
                pb = pb_by_roll.get(roll, {})
                pc = pc_by_roll.get(roll, {})

                row = {
                    "Roll Number": roll, "Name": s["full_name"], "Paper Title": s["paper_title"],
                    "Status": "valid",
                    "Part A Final (50)": pa.get("final_total", 0),
                    "Part A Raw (50)": pa.get("raw_total", 0),
                    "Part A Scaled (5%)": pa.get("scaled_score", 0),
                }
                if pb:
                    row["Part B Raw (130)"] = pb.get("raw_total", 0)
                    row["Part B Final (130)"] = pb.get("final_total", 0)
                    row["Part B Scaled (30%)"] = pb.get("scaled_score", 0)
                else:
                    row["Part B Raw (130)"] = "NO SUBMISSION"
                    row["Part B Final (130)"] = 0
                    row["Part B Scaled (30%)"] = 0
                if pc:
                    row["Part C Score (5)"] = pc.get("total_score", 0)
                    row["Part C Questions Answered"] = pc.get("questions_answered", 0)
                else:
                    row["Part C Score (5)"] = "NO DATA"

                all_flags = pa.get("flags", []) + pb.get("flags", [])
                row["Flags"] = "; ".join(all_flags[:5]) if all_flags else ""
                row["Needs Review"] = "YES" if all_flags else "NO"
                rows.append(row)

            with open(output_dir / "master_scores.json", "w") as f:
                _json.dump(rows, f, indent=2)
            if rows:
                all_fields = list(dict.fromkeys(k for row in rows for k in row.keys()))
                with open(output_dir / "master_scores.csv", "w", newline="") as f:
                    w = csv_mod.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)

            from datetime import datetime
            run_manager.update_meta(run_id, status="complete", phase="complete",
                current_step="Evaluation complete!", completed_at=datetime.now().isoformat())
            return jsonify({"step": "complete", "total_students": len(rows), "next": None})

        else:
            return jsonify({"step": phase, "next": None, "message": f"Unknown phase: {phase}"})

    except Exception as e:
        tb = traceback.format_exc()
        run_manager.update_meta(run_id, status="error", phase="error", error=str(e), traceback=tb[-500:])
        return jsonify({"step": "error", "error": str(e), "traceback": tb[-300:]}), 500


@eval_bp.route("/eval/<run_id>/run-full")
def run_full(run_id):
    """Run the FULL pipeline synchronously (GET endpoint - same as run-sync which works)."""
    import sys, traceback

    meta = run_manager.get_meta(run_id)
    if not meta:
        return "Run not found", 404

    eval_dir = str(run_manager.Config.EVALUATOR_DIR)
    if eval_dir not in sys.path:
        sys.path.insert(0, eval_dir)

    run_dir = run_manager.get_run_dir(run_id)
    output_dir = run_dir / "output"
    uploads_dir = run_dir / "uploads"

    def generate():
        yield "=== FULL PIPELINE START ===\n"

        xlsx_path = uploads_dir / "part_a.xlsx"
        csv_path = uploads_dir / "part_b.csv"
        yield f"Part A: {xlsx_path.exists()}, Part B: {csv_path.exists()}\n"

        # Phase 0
        try:
            yield "--- PHASE 0: Data Cleanup ---\n"
            run_manager.update_meta(run_id, phase="phase0", current_step="Running Phase 0...")
            from phase0_data_cleanup import run_phase0_web
            summary = run_phase0_web(str(xlsx_path), str(csv_path), output_dir)
            valid_count = summary['stats']['total_valid_part_a']
            yield f"Phase 0 OK: {valid_count} valid students, {summary['stats']['total_part_b_submissions']} Part B\n"
            run_manager.update_meta(run_id, phase="phase0_done", total_students=valid_count,
                                   current_step=f"Phase 0 complete: {valid_count} students")
        except Exception as e:
            yield f"Phase 0 FAILED: {traceback.format_exc()}\n"
            run_manager.update_meta(run_id, status="error", error=str(e))
            return

        # Part A
        try:
            yield "\n--- PART A: Evaluation ---\n"
            import agents.part_a_evaluator as pa_eval
            import json, time

            scores_dir = output_dir / "part_a_scores"
            scores_dir.mkdir(parents=True, exist_ok=True)

            from webapp.config import Config
            gt_dir = Config.GROUND_TRUTH_DIR
            gt_dir.mkdir(parents=True, exist_ok=True)

            orig_output = pa_eval.OUTPUT_DIR
            orig_scores = pa_eval.SCORES_DIR
            orig_gt = pa_eval.GROUND_TRUTH_DIR
            pa_eval.OUTPUT_DIR = output_dir
            pa_eval.SCORES_DIR = scores_dir
            pa_eval.GROUND_TRUTH_DIR = gt_dir

            valid_students = summary.get("valid_students", [])
            penalties = summary.get("resubmission_penalties", {})
            all_a_results = []

            import gc

            for i, student in enumerate(valid_students):
                roll = student["roll_number"]
                name = student["full_name"]
                penalty_pct = penalties.get(roll, {}).get("penalty_percentage", 0)
                run_manager.update_meta(run_id, phase="part_a",
                                       current_step=f"Evaluating {roll} ({name}) [{i+1}/{len(valid_students)}]",
                                       current_index=i+1, evaluated_part_a=i)
                try:
                    result = pa_eval.evaluate_student_part_a(student, penalty_pct)
                    # Keep only essential fields to save memory
                    slim_result = {
                        "roll_number": result.get("roll_number"),
                        "full_name": result.get("full_name"),
                        "final_total": result.get("final_total", 0),
                        "raw_total": result.get("raw_total", 0),
                        "scaled_score": result.get("scaled_score", 0),
                        "penalty": result.get("penalty", 0),
                        "flags": result.get("flags", []),
                    }
                    all_a_results.append(slim_result)
                    yield f"  {roll} ({name}): {result.get('final_total', '?')}/50\n"
                    del result
                except Exception as e:
                    yield f"  {roll} ERROR: {e}\n"
                    all_a_results.append({"roll_number": roll, "error": str(e), "final_total": 0, "raw_total": 0, "scaled_score": 0, "flags": ["EVALUATION_ERROR"]})
                gc.collect()
                yield f"  [memory cleaned, continuing...]\n"
                time.sleep(0.5)

            with open(output_dir / "part_a_all_results.json", "w") as f:
                json.dump(all_a_results, f, indent=2, default=str)

            pa_eval.OUTPUT_DIR = orig_output
            pa_eval.SCORES_DIR = orig_scores
            pa_eval.GROUND_TRUTH_DIR = orig_gt

            evaluated_a = sum(1 for r in all_a_results if "error" not in r)
            run_manager.update_meta(run_id, phase="part_a_done", evaluated_part_a=evaluated_a,
                                   current_step=f"Part A complete: {evaluated_a}/{len(valid_students)}")
            yield f"Part A done: {evaluated_a}/{len(valid_students)} evaluated\n"
        except Exception as e:
            yield f"Part A FAILED: {traceback.format_exc()}\n"
            run_manager.update_meta(run_id, current_step=f"Part A error: {e}")

        # Part B
        if summary["stats"]["total_part_b_submissions"] > 0:
            try:
                yield "\n--- PART B: Evaluation ---\n"
                run_manager.update_meta(run_id, phase="part_b", current_step="Starting Part B...")
                # Import and use the pipeline's run_part_b
                from webapp.services.progress import get_progress
                progress = get_progress(run_id)
                if not progress:
                    progress = create_progress(run_id)
                from webapp.services.pipeline import run_part_b as _run_part_b
                _run_part_b(run_id, progress, summary)
                yield "Part B done\n"
                run_manager.update_meta(run_id, phase="part_b_done", current_step="Part B complete")
            except Exception as e:
                yield f"Part B error: {e}\n"
                run_manager.update_meta(run_id, current_step=f"Part B error: {e}")
        else:
            yield "\nNo Part B submissions, skipping\n"

        # Part C
        part_c_path = uploads_dir / "part_c.xlsx"
        if part_c_path.exists():
            try:
                yield "\n--- PART C: Cross-Verification ---\n"
                run_manager.update_meta(run_id, phase="part_c", current_step="Starting Part C...")
                from agents.part_c_evaluator import run_part_c_evaluation
                pc_results = run_part_c_evaluation(str(part_c_path), summary.get("valid_students", []), output_dir)
                evaluated_c = sum(1 for r in pc_results if "error" not in r)
                yield f"Part C done: {evaluated_c} evaluated\n"
                run_manager.update_meta(run_id, phase="part_c_done", evaluated_part_c=evaluated_c,
                                       current_step="Part C complete")
            except Exception as e:
                yield f"Part C error: {e}\n{traceback.format_exc()[-300:]}\n"
                run_manager.update_meta(run_id, current_step=f"Part C error: {e}")
        else:
            yield "\nNo Part C file, skipping\n"

        # Aggregation
        try:
            yield "\n--- AGGREGATION ---\n"
            run_manager.update_meta(run_id, phase="aggregate", current_step="Aggregating...")
            progress = get_progress(run_id) or create_progress(run_id)
            from webapp.services.pipeline import run_aggregation
            run_aggregation(run_id, progress)
            yield "Aggregation done\n"
        except Exception as e:
            yield f"Aggregation error: {e}\n"

        run_manager.update_meta(run_id, status="complete", phase="complete",
                               current_step="Evaluation complete!",
                               completed_at=__import__('datetime').datetime.now().isoformat())
        yield "\n=== ALL DONE ===\n"

    return Response(generate(), mimetype='text/plain',
                   headers={"X-Accel-Buffering": "no"})


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
