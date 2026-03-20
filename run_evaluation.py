#!/usr/bin/env python3
"""
Master Evaluation Orchestrator
Runs the complete evaluation pipeline: Phase 0 -> Phase 1 (on demand) -> Phase 2 -> Phase 3 -> Phase 4

Usage:
    python run_evaluation.py                    # Run everything
    python run_evaluation.py --phase0           # Only Phase 0
    python run_evaluation.py --part-a           # Only Part A evaluation
    python run_evaluation.py --part-b           # Only Part B evaluation
    python run_evaluation.py --part-a-student 230049  # Single student Part A
    python run_evaluation.py --part-b-student 230091  # Single student Part B
    python run_evaluation.py --aggregate        # Only aggregation
"""

import argparse
import json
import os
import sys
import csv
from datetime import datetime
from pathlib import Path

# Ensure we're in the right directory
EVALUATOR_DIR = Path(__file__).parent
os.chdir(str(EVALUATOR_DIR))
sys.path.insert(0, str(EVALUATOR_DIR))

OUTPUT_DIR = EVALUATOR_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def run_phase0():
    """Phase 0: Data Cleanup"""
    from phase0_data_cleanup import main as phase0_main
    return phase0_main()


def run_part_a_single(roll_number: str):
    """Run Part A evaluation for a single student."""
    from agents.part_a_evaluator import evaluate_student_part_a

    summary_path = OUTPUT_DIR / "phase0_summary.json"
    with open(summary_path) as f:
        summary = json.load(f)

    student = next((s for s in summary["valid_students"] if s["roll_number"] == roll_number), None)
    if not student:
        print(f"Student {roll_number} not found in valid submissions")
        return None

    penalties = summary.get("resubmission_penalties", {})
    penalty_pct = penalties.get(roll_number, {}).get("penalty_percentage", 0)

    return evaluate_student_part_a(student, penalty_pct)


def run_part_a_all():
    """Run Part A evaluation for all students."""
    from agents.part_a_evaluator import run_all_part_a
    return run_all_part_a()


def run_part_b_single(roll_number: str):
    """Run Part B evaluation for a single student."""
    from agents.part_b_evaluator import evaluate_student_part_b

    summary_path = OUTPUT_DIR / "phase0_summary.json"
    with open(summary_path) as f:
        summary = json.load(f)

    part_b = [s for s in summary["part_b_students"] if s["roll_number"] == roll_number]
    if not part_b:
        print(f"Student {roll_number} not found in Part B submissions")
        return None

    student_b = part_b[-1]  # Latest submission
    student_a = next((s for s in summary["valid_students"] if s["roll_number"] == roll_number), {})

    if not student_a:
        print(f"Student {roll_number} has no valid Part A - cannot evaluate Part B")
        return None

    # Get ground truth
    gt_dir = OUTPUT_DIR / "ground_truths"
    safe_title = student_a["paper_title"][:60].replace("/", "_").replace(" ", "_")
    gt_path = gt_dir / f"{safe_title}.json"

    if gt_path.exists():
        with open(gt_path) as f:
            ground_truth = json.load(f)
    else:
        from agents.paper_ground_truth import generate_ground_truth
        ground_truth = generate_ground_truth(
            title=student_a["paper_title"],
            venue=student_a["venue"],
            year=student_a.get("year_of_publication", 0),
            method=student_a["primary_method"],
            url=student_a.get("paper_link", ""),
        )
        if ground_truth:
            gt_dir.mkdir(parents=True, exist_ok=True)
            with open(gt_path, "w") as f:
                json.dump(ground_truth, f, indent=2)

    return evaluate_student_part_b(student_b, student_a, ground_truth or {})


def run_part_b_all():
    """Run Part B evaluation for all Part B students."""
    from agents.part_b_evaluator import run_all_part_b
    return run_all_part_b()


def aggregate_scores():
    """Phase 4: Aggregate all scores into a master spreadsheet."""
    print("=" * 70)
    print("PHASE 4: SCORE AGGREGATION")
    print("=" * 70)

    summary_path = OUTPUT_DIR / "phase0_summary.json"
    with open(summary_path) as f:
        summary = json.load(f)

    # Load Part A scores
    part_a_path = OUTPUT_DIR / "part_a_all_results.json"
    part_a_scores = {}
    if part_a_path.exists():
        with open(part_a_path) as f:
            for r in json.load(f):
                part_a_scores[r["roll_number"]] = r

    # Load Part B scores
    part_b_path = OUTPUT_DIR / "part_b_all_results.json"
    part_b_scores = {}
    if part_b_path.exists():
        with open(part_b_path) as f:
            for r in json.load(f):
                part_b_scores[r["roll_number"]] = r

    # Also load individual score files
    part_a_dir = OUTPUT_DIR / "part_a_scores"
    if part_a_dir.exists():
        for f in part_a_dir.glob("*_part_a.json"):
            with open(f) as fh:
                data = json.load(fh)
                roll = data["roll_number"]
                if roll not in part_a_scores:
                    part_a_scores[roll] = data

    part_b_dir = OUTPUT_DIR / "part_b_scores"
    if part_b_dir.exists():
        for f in part_b_dir.glob("*_part_b.json"):
            with open(f) as fh:
                data = json.load(fh)
                roll = data["roll_number"]
                if roll not in part_b_scores:
                    part_b_scores[roll] = data

    # Build master list
    all_students = {}
    for s in summary["valid_students"]:
        roll = s["roll_number"]
        all_students[roll] = {
            "roll_number": roll,
            "full_name": s["full_name"],
            "paper_title": s["paper_title"],
            "venue": s["venue"],
            "method": s["primary_method"],
            "status": "valid",
        }

    for s in summary.get("disqualified_students", []):
        roll = s["roll_number"]
        all_students[roll] = {
            "roll_number": roll,
            "full_name": s["full_name"],
            "paper_title": s["paper_title"],
            "status": "disqualified",
            "disqualified_reason": s.get("disqualified_reason", ""),
        }

    # Merge scores
    rows = []
    for roll, info in sorted(all_students.items()):
        row = {
            "Roll Number": roll,
            "Name": info["full_name"],
            "Paper Title": info["paper_title"],
            "Status": info["status"],
        }

        if info["status"] == "disqualified":
            row["Part A Raw (50)"] = 0
            row["Part A Final (50)"] = 0
            row["Part A Scaled (5%)"] = 0
            row["Part B Raw (130)"] = "N/A (disqualified)"
            row["Part B Final (130)"] = 0
            row["Part B Scaled (30%)"] = 0
            row["Flags"] = info.get("disqualified_reason", "DISQUALIFIED")
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
    csv_path = OUTPUT_DIR / "master_scores.csv"
    if rows:
        # Collect ALL possible fieldnames across all rows
        all_fields = []
        seen = set()
        for row in rows:
            for k in row.keys():
                if k not in seen:
                    all_fields.append(k)
                    seen.add(k)

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    # Write JSON
    json_path = OUTPUT_DIR / "master_scores.json"
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2, default=str)

    # Print summary
    evaluated_a = sum(1 for r in rows if r.get("Part A Final (50)") not in ["NOT EVALUATED", 0, "N/A"])
    evaluated_b = sum(1 for r in rows if r.get("Part B Final (130)") not in ["NOT EVALUATED", "NO SUBMISSION", 0, "N/A"])
    flagged = sum(1 for r in rows if r.get("Needs Review") == "YES")

    print(f"\n  Master scores written to: {csv_path}")
    print(f"  Total students: {len(rows)}")
    print(f"  Part A evaluated: {evaluated_a}")
    print(f"  Part B evaluated: {evaluated_b}")
    print(f"  Flagged for review: {flagged}")

    return rows


def main():
    parser = argparse.ArgumentParser(description="NST Exam Evaluation Pipeline")
    parser.add_argument("--phase0", action="store_true", help="Run Phase 0 only")
    parser.add_argument("--part-a", action="store_true", help="Run Part A evaluation")
    parser.add_argument("--part-b", action="store_true", help="Run Part B evaluation")
    parser.add_argument("--part-a-student", type=str, help="Evaluate single student Part A")
    parser.add_argument("--part-b-student", type=str, help="Evaluate single student Part B")
    parser.add_argument("--aggregate", action="store_true", help="Run score aggregation only")
    parser.add_argument("--all", action="store_true", help="Run everything")

    args = parser.parse_args()

    # Default to --all if no args
    run_all = args.all or not any([
        args.phase0, args.part_a, args.part_b,
        args.part_a_student, args.part_b_student, args.aggregate
    ])

    print(f"NST Advanced ML Exam Evaluator")
    print(f"Started at: {datetime.now().isoformat()}")
    print(f"{'='*70}")

    if args.phase0 or run_all:
        run_phase0()

    if args.part_a_student:
        run_part_a_single(args.part_a_student)
    elif args.part_a or run_all:
        run_part_a_all()

    if args.part_b_student:
        run_part_b_single(args.part_b_student)
    elif args.part_b or run_all:
        run_part_b_all()

    if args.aggregate or run_all:
        aggregate_scores()

    print(f"\n{'='*70}")
    print(f"Completed at: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
