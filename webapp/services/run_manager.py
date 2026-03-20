"""Manages evaluation run directories and metadata."""
import json
import shutil
from datetime import datetime
from pathlib import Path

from webapp.config import Config


def get_runs_dir() -> Path:
    d = Config.RUNS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_run(part_a_filename: str = "", part_b_filename: str = "") -> str:
    """Create a new run directory and return the run_id."""
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = get_runs_dir() / run_id
    (run_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (run_dir / "output" / "part_a_scores").mkdir(parents=True, exist_ok=True)
    (run_dir / "output" / "part_b_scores").mkdir(parents=True, exist_ok=True)
    (run_dir / "output" / "ground_truths").mkdir(parents=True, exist_ok=True)

    meta = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(),
        "status": "created",
        "part_a_file": part_a_filename,
        "part_b_file": part_b_filename,
        "total_students": 0,
        "evaluated_part_a": 0,
        "evaluated_part_b": 0,
        "completed_at": None,
    }
    with open(run_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    return run_id


def get_run_dir(run_id: str) -> Path:
    return get_runs_dir() / run_id


def get_run_output_dir(run_id: str) -> Path:
    return get_runs_dir() / run_id / "output"


def update_meta(run_id: str, **kwargs):
    """Update run metadata."""
    meta_path = get_run_dir(run_id) / "meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
    else:
        meta = {"run_id": run_id}
    meta.update(kwargs)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


def get_meta(run_id: str) -> dict:
    meta_path = get_run_dir(run_id) / "meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            return json.load(f)
    return {}


def list_runs() -> list:
    """List all runs sorted by creation time (newest first)."""
    runs_dir = get_runs_dir()
    runs = []
    for d in sorted(runs_dir.iterdir(), reverse=True):
        if d.is_dir() and (d / "meta.json").exists():
            meta = get_meta(d.name)
            # Check if results exist
            output_dir = d / "output"
            meta["has_results"] = (output_dir / "master_scores.json").exists()
            meta["has_phase0"] = (output_dir / "phase0_summary.json").exists()
            runs.append(meta)
    return runs


def get_results_data(run_id: str) -> dict:
    """Load all results data for a run."""
    output_dir = get_run_output_dir(run_id)
    data = {"run_id": run_id}

    # Phase 0 summary
    p0 = output_dir / "phase0_summary.json"
    if p0.exists():
        with open(p0) as f:
            data["phase0"] = json.load(f)

    # Master scores
    ms = output_dir / "master_scores.json"
    if ms.exists():
        with open(ms) as f:
            data["master_scores"] = json.load(f)

    # Part A results
    pa = output_dir / "part_a_all_results.json"
    if pa.exists():
        with open(pa) as f:
            data["part_a_results"] = json.load(f)

    # Part B results
    pb = output_dir / "part_b_all_results.json"
    if pb.exists():
        with open(pb) as f:
            data["part_b_results"] = json.load(f)

    return data


def get_student_detail(run_id: str, roll: str) -> dict:
    """Load detailed results for a specific student."""
    output_dir = get_run_output_dir(run_id)
    detail = {"roll_number": roll}

    # Part A
    pa_path = output_dir / "part_a_scores" / f"{roll}_part_a.json"
    if pa_path.exists():
        with open(pa_path) as f:
            detail["part_a"] = json.load(f)

    # Part B
    pb_path = output_dir / "part_b_scores" / f"{roll}_part_b.json"
    if pb_path.exists():
        with open(pb_path) as f:
            detail["part_b"] = json.load(f)

    # Student info from phase0
    p0 = output_dir / "phase0_summary.json"
    if p0.exists():
        with open(p0) as f:
            summary = json.load(f)
        for s in summary.get("valid_students", []):
            if s["roll_number"] == roll:
                detail["info"] = s
                break
        if "info" not in detail:
            for s in summary.get("disqualified_students", []):
                if s["roll_number"] == roll:
                    detail["info"] = s
                    detail["info"]["status"] = "disqualified"
                    break

    return detail
