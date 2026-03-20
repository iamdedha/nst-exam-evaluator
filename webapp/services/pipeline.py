"""
Pipeline service: bridges Flask web app with the existing evaluation pipeline.
Wraps evaluator functions, redirects output directories, captures progress.
"""
import json
import sys
import os
import csv
import threading
import io
import time
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

from webapp.config import Config
from webapp.services.progress import RunProgress
from webapp.services import run_manager

# Lock to prevent concurrent evaluations (module-level variable safety)
_eval_lock = threading.Lock()

EVALUATOR_DIR = Config.EVALUATOR_DIR


@contextmanager
def _redirect_output(progress: RunProgress):
    """Capture print statements and route them to progress log."""
    class ProgressWriter:
        def __init__(self, original, progress):
            self.original = original
            self.progress = progress

        def write(self, text):
            self.original.write(text)
            text = text.strip()
            if text:
                self.progress.log(text)

        def flush(self):
            self.original.flush()

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = ProgressWriter(old_stdout, progress)
    sys.stderr = ProgressWriter(old_stderr, progress)
    try:
        yield
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def _setup_sys_path():
    """Ensure evaluator modules are importable."""
    eval_str = str(EVALUATOR_DIR)
    if eval_str not in sys.path:
        sys.path.insert(0, eval_str)


def run_phase0(run_id: str, progress: RunProgress) -> dict:
    """Run Phase 0 data cleanup for a web evaluation run."""
    _setup_sys_path()

    run_dir = run_manager.get_run_dir(run_id)
    output_dir = run_dir / "output"
    uploads_dir = run_dir / "uploads"

    xlsx_path = uploads_dir / "part_a.xlsx"
    csv_path = uploads_dir / "part_b.csv"

    if not xlsx_path.exists():
        raise FileNotFoundError(f"Part A file not found: {xlsx_path}")
    if not csv_path.exists():
        raise FileNotFoundError(f"Part B file not found: {csv_path}")

    progress.update(phase="phase0", current_step="Parsing submissions...")

    from phase0_data_cleanup import run_phase0_web
    summary = run_phase0_web(str(xlsx_path), str(csv_path), output_dir)

    total = summary["stats"]["total_valid_part_a"]
    progress.update(
        total_students=total,
        current_step="Phase 0 complete",
        phase_results={
            "phase0": {
                "valid": summary["stats"]["total_valid_part_a"],
                "disqualified": summary["stats"]["total_disqualified"],
                "penalties": summary["stats"]["students_with_resubmission_penalty"],
                "part_b": summary["stats"]["total_part_b_submissions"],
            }
        }
    )

    run_manager.update_meta(run_id, status="phase0_complete",
                           total_students=total)
    return summary


def run_part_a(run_id: str, progress: RunProgress, summary: dict):
    """Run Part A evaluation for all valid students."""
    _setup_sys_path()
    import agents.part_a_evaluator as pa_eval

    output_dir = run_manager.get_run_output_dir(run_id)
    scores_dir = output_dir / "part_a_scores"
    scores_dir.mkdir(parents=True, exist_ok=True)

    # Use shared ground truth cache
    gt_dir = Config.GROUND_TRUTH_DIR
    gt_dir.mkdir(parents=True, exist_ok=True)

    # Monkey-patch module-level directories
    orig_output = pa_eval.OUTPUT_DIR
    orig_scores = pa_eval.SCORES_DIR
    orig_gt = pa_eval.GROUND_TRUTH_DIR

    try:
        pa_eval.OUTPUT_DIR = output_dir
        pa_eval.SCORES_DIR = scores_dir
        pa_eval.GROUND_TRUTH_DIR = gt_dir

        valid_students = summary.get("valid_students", [])
        penalties = summary.get("resubmission_penalties", {})

        progress.update(
            phase="part_a",
            total_students=len(valid_students),
            current_index=0,
            current_step="Starting Part A evaluation..."
        )

        all_results = []
        for i, student in enumerate(valid_students):
            roll = student["roll_number"]
            name = student["full_name"]
            penalty_pct = penalties.get(roll, {}).get("penalty_percentage", 0)

            progress.update(
                current_index=i + 1,
                current_roll=roll,
                current_name=name,
                current_step=f"Evaluating {roll} ({name})"
            )

            try:
                result = pa_eval.evaluate_student_part_a(student, penalty_pct)
                all_results.append(result)
            except Exception as e:
                progress.log(f"ERROR evaluating {roll}: {e}")
                all_results.append({
                    "roll_number": roll,
                    "error": str(e),
                    "final_total": 0,
                    "raw_total": 0,
                    "scaled_score": 0,
                    "flags": ["EVALUATION_ERROR"],
                })

            time.sleep(0.5)  # Rate limit buffer

        # Save aggregate results
        with open(output_dir / "part_a_all_results.json", "w") as f:
            json.dump(all_results, f, indent=2, default=str)

        evaluated = sum(1 for r in all_results if "error" not in r)
        avg_score = sum(r.get("final_total", 0) for r in all_results) / max(len(all_results), 1)

        pr = progress.phase_results.copy()
        pr["part_a"] = {
            "evaluated": evaluated,
            "total": len(valid_students),
            "avg_score": round(avg_score, 1),
        }
        progress.update(phase_results=pr, current_step="Part A complete")

        run_manager.update_meta(run_id, evaluated_part_a=evaluated)
        return all_results

    finally:
        pa_eval.OUTPUT_DIR = orig_output
        pa_eval.SCORES_DIR = orig_scores
        pa_eval.GROUND_TRUTH_DIR = orig_gt


def run_part_b(run_id: str, progress: RunProgress, summary: dict):
    """Run Part B evaluation for all Part B students."""
    _setup_sys_path()
    import agents.part_b_evaluator as pb_eval
    from agents.github_checker import parse_github_url, check_repo_exists
    from agents.paper_ground_truth import generate_ground_truth

    output_dir = run_manager.get_run_output_dir(run_id)
    scores_dir = output_dir / "part_b_scores"
    scores_dir.mkdir(parents=True, exist_ok=True)

    gt_dir = Config.GROUND_TRUTH_DIR
    gt_dir.mkdir(parents=True, exist_ok=True)

    orig_output = pb_eval.OUTPUT_DIR
    orig_scores = pb_eval.SCORES_DIR
    orig_gt = getattr(pb_eval, 'GROUND_TRUTH_DIR', None)

    try:
        pb_eval.OUTPUT_DIR = output_dir
        pb_eval.SCORES_DIR = scores_dir

        part_b_students = summary.get("part_b_students", [])
        valid_a = {s["roll_number"]: s for s in summary.get("valid_students", [])}

        # Deduplicate Part B (keep latest per roll)
        by_roll = {}
        for s in part_b_students:
            by_roll[s["roll_number"]] = s

        progress.update(
            phase="part_b",
            total_students=len(by_roll),
            current_index=0,
            current_step="Starting Part B evaluation..."
        )

        all_results = []
        for i, (roll, student_b) in enumerate(by_roll.items()):
            student_a = valid_a.get(roll, {})
            if not student_a:
                progress.log(f"SKIP {roll}: No valid Part A")
                continue

            progress.update(
                current_index=i + 1,
                current_roll=roll,
                current_name=student_b["full_name"],
                current_step=f"Evaluating Part B: {roll} ({student_b['full_name']})"
            )

            # Load or generate ground truth
            safe_title = student_a["paper_title"][:60].replace("/", "_").replace(" ", "_")
            gt_path = gt_dir / f"{safe_title}.json"

            if gt_path.exists():
                with open(gt_path) as f:
                    ground_truth = json.load(f)
            else:
                progress.log(f"Generating ground truth for: {student_a['paper_title'][:50]}")
                ground_truth = generate_ground_truth(
                    title=student_a["paper_title"],
                    venue=student_a["venue"],
                    year=student_a.get("year_of_publication", 0),
                    method=student_a["primary_method"],
                    url=student_a.get("paper_link", ""),
                )
                if ground_truth:
                    with open(gt_path, "w") as f:
                        json.dump(ground_truth, f, indent=2)

            try:
                result = pb_eval.evaluate_student_part_b(student_b, student_a, ground_truth or {})
                all_results.append(result)
            except Exception as e:
                progress.log(f"ERROR evaluating Part B {roll}: {e}")
                all_results.append({
                    "roll_number": roll,
                    "error": str(e),
                    "final_total": 0,
                    "flags": ["EVALUATION_ERROR"],
                })

            time.sleep(1)

        with open(output_dir / "part_b_all_results.json", "w") as f:
            json.dump(all_results, f, indent=2, default=str)

        evaluated = sum(1 for r in all_results if "error" not in r)
        pr = progress.phase_results.copy()
        pr["part_b"] = {"evaluated": evaluated, "total": len(by_roll)}
        progress.update(phase_results=pr, current_step="Part B complete")

        run_manager.update_meta(run_id, evaluated_part_b=evaluated)
        return all_results

    finally:
        pb_eval.OUTPUT_DIR = orig_output
        pb_eval.SCORES_DIR = orig_scores
        if orig_gt is not None:
            pb_eval.GROUND_TRUTH_DIR = orig_gt


def run_aggregation(run_id: str, progress: RunProgress):
    """Aggregate all scores into master CSV/JSON."""
    _setup_sys_path()

    output_dir = run_manager.get_run_output_dir(run_id)
    progress.update(phase="aggregate", current_step="Aggregating scores...")

    summary_path = output_dir / "phase0_summary.json"
    with open(summary_path) as f:
        summary = json.load(f)

    # Load Part A scores
    part_a_scores = {}
    pa_path = output_dir / "part_a_all_results.json"
    if pa_path.exists():
        with open(pa_path) as f:
            for r in json.load(f):
                part_a_scores[r["roll_number"]] = r

    pa_dir = output_dir / "part_a_scores"
    if pa_dir.exists():
        for fp in pa_dir.glob("*_part_a.json"):
            with open(fp) as fh:
                data = json.load(fh)
                roll = data["roll_number"]
                if roll not in part_a_scores:
                    part_a_scores[roll] = data

    # Load Part B scores
    part_b_scores = {}
    pb_path = output_dir / "part_b_all_results.json"
    if pb_path.exists():
        with open(pb_path) as f:
            for r in json.load(f):
                part_b_scores[r["roll_number"]] = r

    pb_dir = output_dir / "part_b_scores"
    if pb_dir.exists():
        for fp in pb_dir.glob("*_part_b.json"):
            with open(fp) as fh:
                data = json.load(fh)
                roll = data["roll_number"]
                if roll not in part_b_scores:
                    part_b_scores[roll] = data

    # Build master list
    all_students = {}
    for s in summary["valid_students"]:
        roll = s["roll_number"]
        all_students[roll] = {
            "roll_number": roll, "full_name": s["full_name"],
            "paper_title": s["paper_title"], "status": "valid",
        }

    for s in summary.get("disqualified_students", []):
        roll = s["roll_number"]
        all_students[roll] = {
            "roll_number": roll, "full_name": s["full_name"],
            "paper_title": s["paper_title"], "status": "disqualified",
            "disqualified_reason": s.get("disqualified_reason", ""),
        }

    rows = []
    for roll, info in sorted(all_students.items()):
        row = {
            "Roll Number": roll,
            "Name": info["full_name"],
            "Paper Title": info["paper_title"],
            "Status": info["status"],
        }

        if info["status"] == "disqualified":
            row.update({
                "Part A Raw (50)": 0, "Part A Final (50)": 0,
                "Part A Scaled (5%)": 0, "Part B Raw (130)": "N/A",
                "Part B Final (130)": 0, "Part B Scaled (30%)": 0,
                "Flags": info.get("disqualified_reason", "DISQUALIFIED"),
            })
        else:
            pa = part_a_scores.get(roll, {})
            row["Part A Raw (50)"] = pa.get("raw_total", "NOT EVALUATED")
            row["Part A Penalty"] = pa.get("penalty", 0)
            row["Part A Final (50)"] = pa.get("final_total", "NOT EVALUATED")
            row["Part A Scaled (5%)"] = pa.get("scaled_score", "NOT EVALUATED")

            pb = part_b_scores.get(roll, {})
            if pb:
                row["Part B Raw (130)"] = pb.get("raw_total", "NOT EVALUATED")
                row["Part B Penalty"] = pb.get("structure_penalty", 0)
                row["Part B Final (130)"] = pb.get("final_total", "NOT EVALUATED")
                row["Part B Scaled (30%)"] = pb.get("scaled_score", "NOT EVALUATED")
                row["Part B Q1 (25)"] = pb.get("q1", {}).get("total", "")
                row["Part B Q2 (40)"] = pb.get("q2", {}).get("total", "")
                row["Part B Q3 (35)"] = pb.get("q3", {}).get("total", "")
                row["Part B Q4 (30)"] = pb.get("q4", {}).get("total", "")
            else:
                row["Part B Raw (130)"] = "NO SUBMISSION"
                row["Part B Final (130)"] = 0
                row["Part B Scaled (30%)"] = 0

            flags = pa.get("flags", []) + pb.get("flags", [])
            row["Flags"] = "; ".join(flags[:5]) if flags else ""
            row["Needs Review"] = "YES" if flags else "NO"

        rows.append(row)

    # Write CSV
    if rows:
        all_fields = []
        seen = set()
        for row in rows:
            for k in row.keys():
                if k not in seen:
                    all_fields.append(k)
                    seen.add(k)

        with open(output_dir / "master_scores.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    # Write JSON
    with open(output_dir / "master_scores.json", "w") as f:
        json.dump(rows, f, indent=2, default=str)

    progress.update(current_step="Aggregation complete")
    run_manager.update_meta(run_id, status="complete",
                           completed_at=datetime.now().isoformat())
    return rows


def run_full_pipeline(run_id: str, progress: RunProgress):
    """Run the complete evaluation pipeline in a background thread."""
    if not _eval_lock.acquire(blocking=False):
        progress.update(phase="error", error="Another evaluation is already running")
        return

    try:
        progress.update(phase="starting", started_at=datetime.now())
        run_manager.update_meta(run_id, status="running")

        with _redirect_output(progress):
            # Phase 0
            summary = run_phase0(run_id, progress)

            # Part A
            run_part_a(run_id, progress, summary)

            # Part B
            if summary["stats"]["total_part_b_submissions"] > 0:
                run_part_b(run_id, progress, summary)
            else:
                progress.log("No Part B submissions to evaluate")

            # Aggregation
            run_aggregation(run_id, progress)

        progress.update(phase="complete", completed_at=datetime.now(),
                       current_step="Evaluation complete!")

    except Exception as e:
        import traceback
        progress.update(phase="error", error=str(e))
        progress.log(f"FATAL ERROR: {traceback.format_exc()}")
        run_manager.update_meta(run_id, status="error", error=str(e))
    finally:
        _eval_lock.release()
