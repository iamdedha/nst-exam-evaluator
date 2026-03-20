"""
Phase 2: Part A Evaluation Pipeline
Evaluates each student's Part A submission against the rubric (50 marks).

Tier 1: Deterministic checks (no LLM)
Tier 2: LLM-based evaluation using paper ground truth
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agents.llm_client import call_llm_json, call_llm
from agents.github_checker import validate_part_a_repo
from agents.paper_ground_truth import generate_ground_truth
from config.core_a_star_venues import CORE_A_STAR_VENUES, VALID_YEARS

OUTPUT_DIR = Path(__file__).parent.parent.parent / "evaluator" / "output"
GROUND_TRUTH_DIR = OUTPUT_DIR / "ground_truths"
SCORES_DIR = OUTPUT_DIR / "part_a_scores"
SCORES_DIR.mkdir(parents=True, exist_ok=True)

# Part A Rubric (50 marks total)
RUBRIC = {
    "paper_validity_venue": 5,
    "paper_validity_year": 4,
    "paper_validity_method_alignment": 4,
    "paper_validity_paper_type": 2,
    "reproducibility_dataset_availability": 5,
    "reproducibility_compute_feasibility": 5,
    "reproducibility_experimental_scope": 5,
    "llm_disclosure_json_validity": 4,
    "llm_disclosure_completeness": 3,
    "llm_disclosure_verification": 3,
    "top5_prompts_analytical_depth": 6,
    "top5_prompts_relevance": 4,
}


def evaluate_tier1_deterministic(student: dict, repo_result: dict, ground_truth: dict) -> dict:
    """
    Tier 1: Deterministic checks that don't need LLM.
    Returns scores and flags.
    """
    scores = {}
    flags = []
    details = {}

    # 1. Paper Validity: Year (4 marks)
    year = student.get("year_of_publication")
    if year and year in VALID_YEARS:
        scores["paper_validity_year"] = 4
        details["year"] = f"Year {year} is valid (2009-2012)"
    else:
        scores["paper_validity_year"] = 0
        details["year"] = f"Year {year} is NOT in 2009-2012 range"
        flags.append(f"INVALID_YEAR: {year}")

    # 2. Paper Validity: Venue (5 marks)
    venue = student.get("venue", "").lower().strip()
    gt_venue_valid = ground_truth.get("venue_is_core_a_star", None)
    venue_match = any(v in venue or venue in v for v in CORE_A_STAR_VENUES)

    if gt_venue_valid is True or venue_match:
        scores["paper_validity_venue"] = 5
        details["venue"] = f"Venue '{student['venue']}' is CORE A*"
    elif gt_venue_valid is False:
        scores["paper_validity_venue"] = 0
        details["venue"] = f"Venue '{student['venue']}' is NOT CORE A*"
        flags.append(f"INVALID_VENUE: {student['venue']}")
    else:
        scores["paper_validity_venue"] = 0
        details["venue"] = f"Venue '{student['venue']}' - unable to verify"
        flags.append(f"VENUE_UNVERIFIED: {student['venue']}")

    # 3. LLM Disclosure: JSON Validity (4 marks)
    json_schema = repo_result.get("checks", {}).get("llm_json_schema", {})
    json_valid = repo_result.get("checks", {}).get("llm_json_valid", False)
    json_exists = repo_result.get("checks", {}).get("llm_json_exists", False)

    if not json_exists:
        scores["llm_disclosure_json_validity"] = 0
        details["json_validity"] = "llm_usage_partA.json not found in repo"
        flags.append("LLM_JSON_MISSING")
    elif not json_valid:
        scores["llm_disclosure_json_validity"] = 0
        details["json_validity"] = "JSON file exists but is not valid JSON"
        flags.append("LLM_JSON_INVALID")
    else:
        # Check required sections exist
        required_sections = [
            "has_student_metadata", "has_llm_tools_used",
            "has_interaction_log", "has_top_5_prompts",
            "has_student_declaration"
        ]
        sections_present = sum(1 for s in required_sections if json_schema.get(s, False))
        score = round(4 * sections_present / len(required_sections))
        scores["llm_disclosure_json_validity"] = score
        details["json_validity"] = f"{sections_present}/{len(required_sections)} required sections present"

    # 4. LLM Disclosure: Completeness (3 marks)
    if json_valid and json_schema:
        log_count = json_schema.get("interaction_log_count", 0)
        has_required_fields = json_schema.get("log_has_required_fields", False)

        if log_count > 0 and has_required_fields:
            scores["llm_disclosure_completeness"] = 3
            details["completeness"] = f"{log_count} interactions logged with required fields"
        elif log_count > 0:
            scores["llm_disclosure_completeness"] = 2
            details["completeness"] = f"{log_count} interactions but missing some required fields"
        else:
            scores["llm_disclosure_completeness"] = 1
            details["completeness"] = "Interaction log empty or missing"
    else:
        scores["llm_disclosure_completeness"] = 0
        details["completeness"] = "JSON not available for completeness check"

    # 5. LLM Disclosure: Verification (3 marks)
    if json_valid and json_schema:
        has_declaration = json_schema.get("has_student_declaration", False)
        acknowledged = json_schema.get("declaration_acknowledged", False)
        has_top5 = json_schema.get("top_5_has_5", False)

        v_score = 0
        if has_declaration:
            v_score += 1
        if acknowledged:
            v_score += 1
        if has_top5:
            v_score += 1
        scores["llm_disclosure_verification"] = v_score
        details["verification"] = f"Declaration: {has_declaration}, Acknowledged: {acknowledged}, Top5: {has_top5}"
    else:
        scores["llm_disclosure_verification"] = 0
        details["verification"] = "JSON not available"

    return {
        "scores": scores,
        "flags": flags,
        "details": details,
    }


def evaluate_tier2_llm(student: dict, ground_truth: dict, llm_json_data: dict = None) -> dict:
    """
    Tier 2: LLM-based evaluation using ground truth.
    Evaluates method alignment, paper type, reproducibility, and prompt quality.
    """
    scores = {}
    flags = []
    details = {}

    # Build context from ground truth
    gt_summary = json.dumps({
        k: v for k, v in ground_truth.items()
        if not k.startswith("_") and k not in ["algorithm_steps", "key_equations"]
    }, indent=2, default=str)

    # --- Paper Validity: Method Alignment (4 marks) ---
    method_valid = ground_truth.get("method_category_valid", None)
    if method_valid is True:
        scores["paper_validity_method_alignment"] = 4
        details["method_alignment"] = f"Method '{ground_truth.get('method_category')}' aligns with ARIMA/GMM/SVM"
    elif method_valid is False:
        scores["paper_validity_method_alignment"] = 0
        details["method_alignment"] = f"Method '{ground_truth.get('method_category')}' does NOT align"
        flags.append("METHOD_MISALIGNMENT")
    else:
        scores["paper_validity_method_alignment"] = 2
        details["method_alignment"] = "Could not determine from ground truth - partial marks given"

    # --- Paper Validity: Paper Type (2 marks) ---
    is_dataset = ground_truth.get("is_dataset_benchmark_system_paper", False)
    is_survey = ground_truth.get("is_survey", False)
    is_dl = ground_truth.get("is_deep_learning", False)

    if is_dataset or is_survey or is_dl:
        scores["paper_validity_paper_type"] = 0
        reasons = []
        if is_dataset:
            reasons.append("dataset/benchmark paper")
        if is_survey:
            reasons.append("survey paper")
        if is_dl:
            reasons.append("deep learning paper")
        details["paper_type"] = f"Invalid: {', '.join(reasons)}"
        flags.append(f"INVALID_PAPER_TYPE: {', '.join(reasons)}")
    else:
        scores["paper_validity_paper_type"] = 2
        details["paper_type"] = "Valid methodological paper"

    # --- Reproducibility: Dataset Availability (5 marks) ---
    dataset_available = ground_truth.get("dataset_publicly_available", None)
    if dataset_available is True:
        scores["reproducibility_dataset_availability"] = 5
        details["dataset"] = f"Datasets: {ground_truth.get('datasets_used', [])}"
    elif dataset_available is False:
        scores["reproducibility_dataset_availability"] = 2
        details["dataset"] = "Dataset not publicly available, but toy substitutes may work"
    else:
        scores["reproducibility_dataset_availability"] = 3
        details["dataset"] = "Dataset availability uncertain"

    # --- Reproducibility: Compute Feasibility (5 marks) ---
    compute = ground_truth.get("compute_requirements", "")
    if "CPU" in compute.upper():
        scores["reproducibility_compute_feasibility"] = 5
        details["compute"] = "CPU feasible"
    elif "GPU_PREFERRED" in compute.upper():
        scores["reproducibility_compute_feasibility"] = 3
        details["compute"] = "GPU preferred but CPU possible"
    elif "GPU_REQUIRED" in compute.upper():
        scores["reproducibility_compute_feasibility"] = 0
        details["compute"] = "GPU required - not feasible for exam"
        flags.append("COMPUTE_GPU_REQUIRED")
    else:
        scores["reproducibility_compute_feasibility"] = 3
        details["compute"] = "Compute requirements uncertain"

    # --- Reproducibility: Experimental Scope (5 marks) ---
    repro = ground_truth.get("reproducibility_assessment", "")
    if "EASY" in repro.upper():
        scores["reproducibility_experimental_scope"] = 5
        details["scope"] = "Easy to reproduce at student level"
    elif "MODERATE" in repro.upper():
        scores["reproducibility_experimental_scope"] = 4
        details["scope"] = "Moderate difficulty"
    elif "HARD" in repro.upper():
        scores["reproducibility_experimental_scope"] = 2
        details["scope"] = "Hard to reproduce - may struggle"
        flags.append("HARD_TO_REPRODUCE")
    else:
        scores["reproducibility_experimental_scope"] = 3
        details["scope"] = "Reproducibility uncertain"

    # --- Top-5 Prompts: Analytical Depth & Relevance (6 + 4 = 10 marks) ---
    if llm_json_data and "top_5_prompts" in llm_json_data:
        prompts = llm_json_data["top_5_prompts"]
        if isinstance(prompts, list) and len(prompts) > 0:
            prompts_text = json.dumps(prompts, indent=2)

            prompt_eval = call_llm_json(
                f"""Evaluate these top-5 prompts from a student's LLM usage disclosure for a research paper analysis exam.

Paper Title: {student['paper_title']}
Method Category: {student['primary_method']}

Student's Top-5 Prompts:
{prompts_text}

Evaluate on TWO criteria and return JSON:

1. **Analytical Depth** (0-6 marks): Do prompts demonstrate analytical intent?
   - 5-6: Prompts ask about failure modes, trade-offs, when/why things work, limitations
   - 3-4: Prompts show some analytical thinking but are partly generic
   - 0-2: Prompts are superficial ("explain X", "summarize Y")

2. **Relevance** (0-4 marks): Are prompts relevant to paper selection and feasibility?
   - 3-4: Prompts directly relate to assessing paper feasibility, reproducibility, understanding
   - 1-2: Somewhat relevant but generic
   - 0: Not relevant to paper selection process

Return ONLY:
{{"analytical_depth_score": <0-6>, "analytical_depth_reason": "<brief reason>", "relevance_score": <0-4>, "relevance_reason": "<brief reason>"}}""",
                "You are an exam evaluator. Be fair but strict. Give justified scores."
            )

            if "analytical_depth_score" in prompt_eval:
                scores["top5_prompts_analytical_depth"] = min(6, max(0, prompt_eval["analytical_depth_score"]))
                scores["top5_prompts_relevance"] = min(4, max(0, prompt_eval["relevance_score"]))
                details["prompts_depth"] = prompt_eval.get("analytical_depth_reason", "")
                details["prompts_relevance"] = prompt_eval.get("relevance_reason", "")
            else:
                scores["top5_prompts_analytical_depth"] = 3
                scores["top5_prompts_relevance"] = 2
                details["prompts_depth"] = "LLM evaluation failed - default score"
                flags.append("PROMPT_EVAL_FAILED")
        else:
            scores["top5_prompts_analytical_depth"] = 0
            scores["top5_prompts_relevance"] = 0
            details["prompts"] = "No prompts found or empty"
    else:
        scores["top5_prompts_analytical_depth"] = 0
        scores["top5_prompts_relevance"] = 0
        details["prompts"] = "LLM JSON not available for prompt evaluation"

    return {
        "scores": scores,
        "flags": flags,
        "details": details,
    }


def evaluate_student_part_a(student: dict, resubmission_penalty_pct: int = 0) -> dict:
    """
    Full Part A evaluation for a single student.
    Combines Tier 1 + Tier 2 evaluation.
    """
    roll = student["roll_number"]
    print(f"\n{'='*60}")
    print(f"Evaluating: {roll} ({student['full_name']})")
    print(f"Paper: {student['paper_title'][:60]}")
    print(f"{'='*60}")

    result = {
        "roll_number": roll,
        "full_name": student["full_name"],
        "paper_title": student["paper_title"],
        "venue": student["venue"],
        "year": student["year_of_publication"],
        "method": student["primary_method"],
        "github_url": student["github_repo"],
    }

    # Step 1: GitHub repo validation
    print(f"  Checking GitHub repo...")
    repo_result = validate_part_a_repo(student["github_repo"], roll)
    result["repo_checks"] = repo_result

    # Step 2: Get or generate ground truth
    print(f"  Getting paper ground truth...")
    safe_title = student["paper_title"][:60].replace("/", "_").replace(" ", "_")
    gt_path = GROUND_TRUTH_DIR / f"{safe_title}.json"

    if gt_path.exists():
        with open(gt_path) as f:
            ground_truth = json.load(f)
        print(f"  Using cached ground truth")
    else:
        ground_truth = generate_ground_truth(
            title=student["paper_title"],
            venue=student["venue"],
            year=student["year_of_publication"],
            method=student["primary_method"],
            url=student["paper_link"],
        )
        if ground_truth and "_parse_error" not in ground_truth:
            GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
            with open(gt_path, "w") as f:
                json.dump(ground_truth, f, indent=2)

    result["ground_truth_available"] = bool(ground_truth and "_parse_error" not in ground_truth)

    # Step 3: Tier 1 - Deterministic evaluation
    print(f"  Running Tier 1 (deterministic) evaluation...")
    tier1 = evaluate_tier1_deterministic(student, repo_result, ground_truth)
    result["tier1"] = tier1

    # Step 4: Tier 2 - LLM evaluation
    print(f"  Running Tier 2 (LLM) evaluation...")
    llm_json_data = repo_result.get("llm_json_data", {})
    tier2 = evaluate_tier2_llm(student, ground_truth, llm_json_data)
    result["tier2"] = tier2

    # Step 5: Combine scores
    all_scores = {**tier1["scores"], **tier2["scores"]}
    all_flags = tier1["flags"] + tier2["flags"] + repo_result.get("flags", [])
    all_details = {**tier1["details"], **tier2["details"]}

    raw_total = sum(all_scores.values())

    # Apply resubmission penalty
    penalty_amount = 0
    if resubmission_penalty_pct > 0:
        penalty_amount = round(raw_total * resubmission_penalty_pct / 100)
        all_flags.append(f"RESUBMISSION_PENALTY: {resubmission_penalty_pct}% = -{penalty_amount} marks")

    final_total = max(0, raw_total - penalty_amount)

    result["scores"] = all_scores
    result["raw_total"] = raw_total
    result["penalty"] = penalty_amount
    result["penalty_reason"] = f"{resubmission_penalty_pct}% resubmission penalty" if penalty_amount else "",
    result["final_total"] = final_total
    result["out_of"] = 50
    result["scaled_score"] = round(final_total / 50 * 5, 2)  # Scaled to 5% of midsem
    result["flags"] = all_flags
    result["details"] = all_details
    result["needs_human_review"] = len(all_flags) > 0

    # Print summary
    print(f"\n  SCORES:")
    for criterion, score in all_scores.items():
        max_marks = RUBRIC.get(criterion, "?")
        print(f"    {criterion}: {score}/{max_marks}")
    print(f"  RAW TOTAL: {raw_total}/50")
    if penalty_amount:
        print(f"  PENALTY: -{penalty_amount} ({resubmission_penalty_pct}%)")
    print(f"  FINAL: {final_total}/50 (scaled: {result['scaled_score']}/5)")
    if all_flags:
        print(f"  FLAGS: {all_flags}")

    # Save individual result
    score_path = SCORES_DIR / f"{roll}_part_a.json"
    with open(score_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    return result


def run_all_part_a():
    """Run Part A evaluation for all valid students."""
    summary_path = OUTPUT_DIR / "phase0_summary.json"
    with open(summary_path) as f:
        summary = json.load(f)

    valid_students = summary["valid_students"]
    penalties = summary.get("resubmission_penalties", {})

    print(f"Starting Part A evaluation for {len(valid_students)} students...")
    print(f"{'='*70}")

    all_results = []
    for i, student in enumerate(valid_students):
        roll = student["roll_number"]
        penalty_pct = penalties.get(roll, {}).get("penalty_percentage", 0)

        result = evaluate_student_part_a(student, penalty_pct)
        all_results.append(result)

        # Rate limiting
        time.sleep(0.5)

        if (i + 1) % 10 == 0:
            print(f"\n>>> Progress: {i+1}/{len(valid_students)} students evaluated <<<\n")

    # Save all results
    all_results_path = OUTPUT_DIR / "part_a_all_results.json"
    with open(all_results_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # Generate summary statistics
    total_scores = [r["final_total"] for r in all_results]
    flagged = [r for r in all_results if r["needs_human_review"]]

    print(f"\n{'='*70}")
    print(f"PART A EVALUATION COMPLETE")
    print(f"{'='*70}")
    print(f"  Students evaluated: {len(all_results)}")
    print(f"  Average score: {sum(total_scores)/len(total_scores):.1f}/50")
    print(f"  Min: {min(total_scores)}/50, Max: {max(total_scores)}/50")
    print(f"  Flagged for review: {len(flagged)}")

    return all_results


if __name__ == "__main__":
    os.chdir(str(Path(__file__).parent.parent))
    run_all_part_a()
