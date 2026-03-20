"""
Phase 3: Part B Evaluation Pipeline
Evaluates each student's Part B submission (130 marks).

Q1: Paper Understanding (25 marks) - markdown only
Q2: Reproduction on Toy Dataset (40 marks) - code + markdown
Q3: Ablation Study (35 marks) - code + markdown
Q4: Report and LLM Usage (30 marks) - PDF + JSON files
Penalty: -20 for repo/notebook structure violation
"""

import json
import os
import sys
import time
import tempfile
import requests
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agents.llm_client import call_llm_json, call_llm
from agents.github_checker import (
    validate_part_b_repo, parse_github_url, fetch_file_content,
    list_directory, check_file_exists
)

try:
    from PyPDF2 import PdfReader
except ImportError:
    from pypdf import PdfReader

OUTPUT_DIR = Path(__file__).parent.parent.parent / "evaluator" / "output"
GROUND_TRUTH_DIR = OUTPUT_DIR / "ground_truths"
SCORES_DIR = OUTPUT_DIR / "part_b_scores"
SCORES_DIR.mkdir(parents=True, exist_ok=True)

def resolve_notebook_name(owner: str, repo: str, task_name: str, branch: str = "main") -> str:
    """
    Resolve notebook path handling naming variations.
    Students may use: task_1_1.ipynb, task1_1.ipynb, Task_1_1.ipynb, etc.
    """
    # Try common naming patterns
    candidates = [
        f"partB/{task_name}.ipynb",                          # task_1_1.ipynb (expected)
        f"partB/{task_name.replace('task_', 'task')}.ipynb", # task1_1.ipynb
        f"partB/{task_name.replace('_', '')}.ipynb",         # task11.ipynb
        f"partB/{task_name.upper()}.ipynb",                  # TASK_1_1.ipynb
        f"partB/{task_name.capitalize()}.ipynb",             # Task_1_1.ipynb
    ]

    for path in candidates:
        result = check_file_exists(owner, repo, path, branch)
        if result.get("exists"):
            return path

    # Last resort: list partB/ and fuzzy match
    files = list_directory(owner, repo, "partB", branch)
    task_num = task_name.replace("task_", "")  # "1_1"
    for f in files:
        fname = f["name"].lower()
        if fname.endswith(".ipynb") and task_num.replace("_", "") in fname.replace("_", ""):
            return f"partB/{f['name']}"

    return f"partB/{task_name}.ipynb"  # Return expected name (will fail gracefully)


EVALUATOR_SYSTEM = """You are an expert ML exam evaluator for a BTech 3rd year Advanced Machine Learning course.
You evaluate student submissions against the paper's ground truth.
Be fair, consistent, and grade based on specificity to the paper (not generic ML knowledge).
A wrong answer that is consistent with the student's own submission scores higher than a correct answer with no trace in the submission."""


def fetch_notebook_content(owner: str, repo: str, nb_path: str, branch: str = "main") -> dict:
    """Fetch and parse a Jupyter notebook, extracting markdown and code cells."""
    content = fetch_file_content(owner, repo, nb_path, branch)
    if not content:
        return {"status": "not_found", "cells": []}

    try:
        nb = json.loads(content)
        cells = []
        for cell in nb.get("cells", []):
            cell_type = cell.get("cell_type", "")
            source = "".join(cell.get("source", []))
            outputs = cell.get("outputs", [])

            # Extract output text
            output_text = ""
            for out in outputs:
                if "text" in out:
                    output_text += "".join(out["text"])
                elif "data" in out:
                    if "text/plain" in out["data"]:
                        output_text += "".join(out["data"]["text/plain"])

            cells.append({
                "type": cell_type,
                "source": source,
                "output": output_text[:2000],  # Truncate long outputs
                "has_output": len(outputs) > 0,
            })

        return {"status": "success", "cells": cells}
    except json.JSONDecodeError:
        return {"status": "parse_error", "cells": []}


def extract_notebook_text(nb_data: dict) -> str:
    """Extract readable text from notebook for LLM evaluation."""
    if nb_data["status"] != "success":
        return ""

    parts = []
    for i, cell in enumerate(nb_data["cells"]):
        if cell["type"] == "markdown":
            parts.append(f"[MARKDOWN CELL {i}]\n{cell['source']}\n")
        elif cell["type"] == "code":
            parts.append(f"[CODE CELL {i}]\n```python\n{cell['source']}\n```")
            if cell["output"]:
                parts.append(f"[OUTPUT]\n{cell['output']}\n")

    return "\n".join(parts)


def evaluate_q1_understanding(owner: str, repo: str, branch: str, ground_truth: dict) -> dict:
    """
    Evaluate Q1: Paper Understanding (25 marks)
    Task 1.1: Core Contribution (8 marks)
    Task 1.2: Key Assumptions (8 marks)
    Task 1.3: Claims to Improve (9 marks)
    """
    results = {"total": 0, "tasks": {}, "flags": []}

    # Fetch all Q1 notebooks (with flexible naming)
    notebooks = {}
    for task in ["task_1_1", "task_1_2", "task_1_3"]:
        nb_path = resolve_notebook_name(owner, repo, task, branch)
        nb = fetch_notebook_content(owner, repo, nb_path, branch)
        notebooks[task] = extract_notebook_text(nb)
        if not notebooks[task]:
            results["flags"].append(f"MISSING_OR_EMPTY: {task}")

    gt_context = json.dumps({
        "core_contribution": ground_truth.get("core_contribution", ""),
        "algorithm_steps": ground_truth.get("algorithm_steps", []),
        "key_assumptions": ground_truth.get("key_assumptions", []),
        "baselines_compared": ground_truth.get("baselines_compared", []),
        "baseline_limitations_identified": ground_truth.get("baseline_limitations_identified", ""),
        "proposed_improvement": ground_truth.get("proposed_improvement", ""),
        "condition_where_baseline_wins": ground_truth.get("condition_where_baseline_wins", ""),
    }, indent=2)

    # --- Task 1.1: Core Contribution (8 marks) ---
    if notebooks["task_1_1"]:
        eval_1_1 = call_llm_json(f"""Evaluate this student's description of a paper's core contribution.

GROUND TRUTH (from the actual paper):
{gt_context}

STUDENT'S SUBMISSION:
{notebooks['task_1_1'][:4000]}

Evaluate on (8 marks total):
- Does the student describe the SPECIFIC method from this paper (not generic SVM/GMM/ARIMA)?
- Does the student follow the step-by-step format with references to equations/figures/sections?
- Is there a final summary sentence about what problem it solves?

Return JSON:
{{"score": <0-8>, "reason": "<2-3 sentence justification>", "is_generic": <true/false>, "references_paper": <true/false>}}""",
            EVALUATOR_SYSTEM
        )
        results["tasks"]["task_1_1"] = {
            "score": min(8, max(0, eval_1_1.get("score", 0))),
            "max": 8,
            "reason": eval_1_1.get("reason", ""),
            "flags": ["GENERIC_DESCRIPTION"] if eval_1_1.get("is_generic") else [],
        }
    else:
        results["tasks"]["task_1_1"] = {"score": 0, "max": 8, "reason": "Notebook not found/empty"}

    # --- Task 1.2: Key Assumptions (8 marks) ---
    if notebooks["task_1_2"]:
        eval_1_2 = call_llm_json(f"""Evaluate this student's identification of key assumptions from their paper.

GROUND TRUTH ASSUMPTIONS:
{json.dumps(ground_truth.get('key_assumptions', []), indent=2)}

STUDENT'S SUBMISSION:
{notebooks['task_1_2'][:4000]}

Evaluate on (8 marks total):
- Did student identify at least 3 assumptions?
- Are assumptions SPECIFIC to the paper's method (not generic "data is i.i.d.")?
- Does each assumption include: the assumption, why needed, violation scenario, paper reference?
- Are assumptions traceable to the paper?

Return JSON:
{{"score": <0-8>, "reason": "<justification>", "num_assumptions": <int>, "are_paper_specific": <true/false>}}""",
            EVALUATOR_SYSTEM
        )
        results["tasks"]["task_1_2"] = {
            "score": min(8, max(0, eval_1_2.get("score", 0))),
            "max": 8,
            "reason": eval_1_2.get("reason", ""),
        }
    else:
        results["tasks"]["task_1_2"] = {"score": 0, "max": 8, "reason": "Notebook not found/empty"}

    # --- Task 1.3: Claims to Improve (9 marks) ---
    if notebooks["task_1_3"]:
        eval_1_3 = call_llm_json(f"""Evaluate this student's analysis of what their paper claims to improve.

GROUND TRUTH:
- Baselines: {ground_truth.get('baselines_compared', [])}
- Baseline limitation: {ground_truth.get('baseline_limitations_identified', '')}
- Proposed improvement: {ground_truth.get('proposed_improvement', '')}
- Condition where baseline wins: {ground_truth.get('condition_where_baseline_wins', '')}

STUDENT'S SUBMISSION:
{notebooks['task_1_3'][:4000]}

Evaluate (9 marks):
- Baseline identified correctly? (2 marks)
- Limitation of baseline explained? (2 marks)
- How proposed method overcomes it? (1 mark)
- Condition where method would NOT outperform baseline? (4 marks - key differentiator)

Return JSON:
{{"score": <0-9>, "baseline_correct": <true/false>, "limitation_explained": <true/false>, "condition_thoughtful": <true/false>, "reason": "<justification>"}}""",
            EVALUATOR_SYSTEM
        )
        results["tasks"]["task_1_3"] = {
            "score": min(9, max(0, eval_1_3.get("score", 0))),
            "max": 9,
            "reason": eval_1_3.get("reason", ""),
        }
    else:
        results["tasks"]["task_1_3"] = {"score": 0, "max": 9, "reason": "Notebook not found/empty"}

    results["total"] = sum(t["score"] for t in results["tasks"].values())
    return results


def evaluate_q2_reproduction(owner: str, repo: str, branch: str, ground_truth: dict) -> dict:
    """
    Evaluate Q2: Reproduction on Toy Dataset (40 marks)
    Task 2.1: Dataset Selection (5 marks)
    Task 2.2: Implementation with Paper References (20 marks)
    Task 2.3: Result, Comparison, Reproducibility (15 marks)
    """
    results = {"total": 0, "tasks": {}, "flags": []}

    notebooks = {}
    for task in ["task_2_1", "task_2_2", "task_2_3"]:
        nb_path = resolve_notebook_name(owner, repo, task, branch)
        nb = fetch_notebook_content(owner, repo, nb_path, branch)
        notebooks[task] = extract_notebook_text(nb)
        if not notebooks[task]:
            results["flags"].append(f"MISSING_OR_EMPTY: {task}")

    gt_context = json.dumps({
        "method_category": ground_truth.get("method_category", ""),
        "suitable_toy_datasets": ground_truth.get("suitable_toy_datasets", []),
        "datasets_used": ground_truth.get("datasets_used", []),
        "algorithm_steps": ground_truth.get("algorithm_steps", []),
        "key_equations": ground_truth.get("key_equations", []),
    }, indent=2)

    # --- Task 2.1: Dataset Selection (5 marks) ---
    if notebooks["task_2_1"]:
        eval_2_1 = call_llm_json(f"""Evaluate this student's dataset selection for reproducing a paper.

GROUND TRUTH:
{gt_context}

STUDENT'S SUBMISSION:
{notebooks['task_2_1'][:3000]}

Evaluate (5 marks):
- Is the dataset appropriate for this paper's method type?
- Does student justify choice in 3-5 sentences?
- Are limitations compared to original dataset mentioned?
- Are preprocessing steps documented?

Return JSON:
{{"score": <0-5>, "dataset_appropriate": <true/false>, "justified": <true/false>, "reason": "<justification>"}}""",
            EVALUATOR_SYSTEM
        )
        results["tasks"]["task_2_1"] = {
            "score": min(5, max(0, eval_2_1.get("score", 0))),
            "max": 5,
            "reason": eval_2_1.get("reason", ""),
        }
    else:
        results["tasks"]["task_2_1"] = {"score": 0, "max": 5, "reason": "Notebook not found/empty"}

    # --- Task 2.2: Implementation (20 marks) - Multi-Agent Evaluation ---
    if notebooks["task_2_2"]:
        from agents.sub_agents import annotation_agent, citation_agent, depth_agent

        sa_annotation = annotation_agent(notebooks["task_2_2"], ground_truth)
        sa_citation = citation_agent(notebooks["task_2_2"], ground_truth)
        sa_depth = depth_agent(notebooks["task_2_2"], ground_truth)

        combined_score = min(20, sa_annotation["score"] + sa_citation["score"] + sa_depth["score"])
        combined_reason = (
            f"Annotations: {sa_annotation['reasoning']} | "
            f"Citations: {sa_citation['reasoning']} | "
            f"Depth: {sa_depth['reasoning']}"
        )

        results["tasks"]["task_2_2"] = {
            "score": combined_score,
            "max": 20,
            "reason": combined_reason,
            "sub_agents": {
                "annotation": sa_annotation,
                "citation": sa_citation,
                "depth": sa_depth,
            },
        }
    else:
        results["tasks"]["task_2_2"] = {"score": 0, "max": 20, "reason": "Notebook not found/empty"}

    # --- Task 2.3: Results & Comparison (15 marks) ---
    if notebooks["task_2_3"]:
        eval_2_3 = call_llm_json(f"""Evaluate this student's results, comparison, and reproducibility checklist.

STUDENT'S SUBMISSION:
{notebooks['task_2_3'][:4000]}

Evaluate (15 marks):
- Reports achieved metric value alongside paper's reported value?
- If numbers differ, provides 3-5 sentence explanation?
- Includes at least one visualization saved to partB/results/?
- Has a "Reproducibility Checklist" cell confirming: random seeds, dependencies, notebooks run clean, no manual steps, hyperparameters defined?

Return JSON:
{{"score": <0-15>, "has_metric_comparison": <true/false>, "has_visualization": <true/false>, "has_repro_checklist": <true/false>, "reason": "<justification>"}}""",
            EVALUATOR_SYSTEM
        )
        results["tasks"]["task_2_3"] = {
            "score": min(15, max(0, eval_2_3.get("score", 0))),
            "max": 15,
            "reason": eval_2_3.get("reason", ""),
        }
    else:
        results["tasks"]["task_2_3"] = {"score": 0, "max": 15, "reason": "Notebook not found/empty"}

    results["total"] = sum(t["score"] for t in results["tasks"].values())
    return results


def evaluate_q3_ablation(owner: str, repo: str, branch: str, ground_truth: dict) -> dict:
    """
    Evaluate Q3: Ablation Study (35 marks)
    Task 3.1: Two-Component Ablation (20 marks)
    Task 3.2: Failure Mode (15 marks)
    """
    results = {"total": 0, "tasks": {}, "flags": []}

    notebooks = {}
    for task in ["task_3_1", "task_3_2"]:
        nb_path = resolve_notebook_name(owner, repo, task, branch)
        nb = fetch_notebook_content(owner, repo, nb_path, branch)
        notebooks[task] = extract_notebook_text(nb)
        if not notebooks[task]:
            results["flags"].append(f"MISSING_OR_EMPTY: {task}")

    gt_context = json.dumps({
        "key_components_for_ablation": ground_truth.get("key_components_for_ablation", []),
        "key_assumptions": ground_truth.get("key_assumptions", []),
        "known_failure_modes": ground_truth.get("known_failure_modes", []),
    }, indent=2)

    # --- Task 3.1: Two-Component Ablation (20 marks) - Multi-Agent Evaluation ---
    if notebooks["task_3_1"]:
        from agents.sub_agents import execution_agent, interpretation_agent

        sa_execution = execution_agent(notebooks["task_3_1"], ground_truth)
        sa_interpretation = interpretation_agent(notebooks["task_3_1"], ground_truth)

        combined_score = min(20, sa_execution["score"] + sa_interpretation["score"])
        combined_reason = (
            f"Execution: {sa_execution['reasoning']} | "
            f"Interpretation: {sa_interpretation['reasoning']}"
        )

        results["tasks"]["task_3_1"] = {
            "score": combined_score,
            "max": 20,
            "reason": combined_reason,
            "sub_agents": {
                "execution": sa_execution,
                "interpretation": sa_interpretation,
            },
        }
    else:
        results["tasks"]["task_3_1"] = {"score": 0, "max": 20, "reason": "Notebook not found/empty"}

    # --- Task 3.2: Failure Mode (15 marks) ---
    if notebooks["task_3_2"]:
        # Also need Task 1.2 to check consistency
        nb_1_2_path = resolve_notebook_name(owner, repo, "task_1_2", branch)
        nb_1_2 = fetch_notebook_content(owner, repo, nb_1_2_path, branch)
        task_1_2_text = extract_notebook_text(nb_1_2)

        eval_3_2 = call_llm_json(f"""Evaluate this student's failure mode analysis.

GROUND TRUTH - Known failure modes and assumptions:
{gt_context}

STUDENT'S TASK 1.2 (Key Assumptions):
{task_1_2_text[:2000]}

STUDENT'S TASK 3.2 (Failure Mode):
{notebooks['task_3_2'][:4000]}

Evaluate (15 marks):
- 5 marks: empirical demonstration (code shows failure, plot/metric)
- 7 marks: explanation linking failure to specific assumption from Task 1.2
- 3 marks: suggested modification to address the failure

Key check: Does the failure mode connect to an assumption identified in Task 1.2?
This is testing CONSISTENCY between parts of the submission.

Return JSON:
{{"score": <0-15>, "has_demonstration": <true/false>, "links_to_assumption": <true/false>, "assumption_from_1_2": "<which assumption>", "has_modification": <true/false>, "reason": "<justification>"}}""",
            EVALUATOR_SYSTEM
        )
        results["tasks"]["task_3_2"] = {
            "score": min(15, max(0, eval_3_2.get("score", 0))),
            "max": 15,
            "reason": eval_3_2.get("reason", ""),
        }
    else:
        results["tasks"]["task_3_2"] = {"score": 0, "max": 15, "reason": "Notebook not found/empty"}

    results["total"] = sum(t["score"] for t in results["tasks"].values())
    return results


def _download_and_extract_pdf(owner: str, repo: str, pdf_path: str, branch: str) -> str:
    """Download a PDF from GitHub and extract its text content."""
    # Try multiple URL patterns
    urls_to_try = [
        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{pdf_path}",
    ]

    for url in urls_to_try:
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "NST-Exam-Evaluator"})
            if resp.status_code == 200 and len(resp.content) > 100:
                # Save to temp file and extract text
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(resp.content)
                    tmp_path = tmp.name

                try:
                    reader = PdfReader(tmp_path)
                    text_parts = []
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text_parts.append(page_text)
                    return "\n\n".join(text_parts)
                finally:
                    os.unlink(tmp_path)
        except Exception as e:
            print(f"    PDF download/extract error for {url}: {e}")
            continue

    return ""


def _find_report_pdf_path(owner: str, repo: str, branch: str) -> str:
    """Find the actual filename of report.pdf (case-insensitive).
    Uses raw downloads as fallback when GitHub API is rate-limited."""
    # Try raw download first (no API rate limit)
    for name in ["report.pdf", "Report.pdf", "REPORT.pdf"]:
        try:
            url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/partB/{name}"
            resp = requests.head(url, timeout=10, headers={"User-Agent": "NST-Exam-Evaluator"})
            if resp.status_code == 200:
                return f"partB/{name}"
        except Exception:
            pass

    # Fallback to GitHub API
    for name in ["report.pdf", "Report.pdf", "REPORT.pdf"]:
        result = check_file_exists(owner, repo, f"partB/{name}", branch)
        if result.get("exists"):
            return f"partB/{name}"

    # List directory and search
    partb_files = list_directory(owner, repo, "partB", branch)
    for f in partb_files:
        if f["name"].lower() == "report.pdf":
            return f"partB/{f['name']}"

    return ""


def evaluate_q4_report(owner: str, repo: str, branch: str, ground_truth: dict) -> dict:
    """
    Evaluate Q4: Report and LLM Usage (30 marks)
    Task 4.1: Report (15 marks) - Download PDF, extract text, evaluate with LLM
    Task 4.2: LLM Usage Disclosure (15 marks)
    """
    results = {"total": 0, "tasks": {}, "flags": []}

    # --- Task 4.1: Report (15 marks) ---
    # Rubric (5 sections x 3 marks each):
    # 1. One-paragraph summary of the paper (3 marks)
    # 2. Reproduction setup and result + honest commentary on gap (3 marks)
    # 3. Two ablation findings and what they reveal (3 marks)
    # 4. Failure mode and explanation (3 marks)
    # 5. Honest reflection: what couldn't be implemented, surprises, revisit plans (3 marks)

    report_pdf_path = _find_report_pdf_path(owner, repo, branch)

    if report_pdf_path:
        print(f"    Found report at: {report_pdf_path}")
        report_text = _download_and_extract_pdf(owner, repo, report_pdf_path, branch)

        if report_text and len(report_text.strip()) > 50:
            print(f"    Extracted {len(report_text)} chars from report PDF")
            # Truncate if very long (max 4 pages ~ 8000 chars typically)
            if len(report_text) > 10000:
                report_text = report_text[:10000] + "\n\n[TRUNCATED]"

            # Build ground truth context for evaluation
            gt_summary = json.dumps({
                "paper_title": ground_truth.get("paper_title", ""),
                "core_contribution": ground_truth.get("core_contribution", ""),
                "key_components_for_ablation": ground_truth.get("key_components_for_ablation", []),
                "known_failure_modes": ground_truth.get("known_failure_modes", []),
                "baselines_compared": ground_truth.get("baselines_compared", []),
            }, indent=2)

            eval_report = call_llm_json(f"""Evaluate this student's report.pdf for their Part B exam submission.

PAPER GROUND TRUTH:
{gt_summary}

STUDENT'S REPORT TEXT (extracted from PDF):
{report_text}

The report is graded on 5 sections, each worth 3 marks (total 15 marks):

1. PAPER SUMMARY (3 marks): Does it include a one-paragraph summary of the paper in the student's own words? Is it specific to this paper (not generic)?

2. REPRODUCTION RESULTS (3 marks): Does it describe the reproduction setup and result? Does it include honest commentary on any gap between their result and the paper's reported value?

3. ABLATION FINDINGS (3 marks): Does it discuss the two ablation findings and what they reveal about the method's components? Are the findings specific and insightful?

4. FAILURE MODE (3 marks): Does it describe the failure mode and provide an explanation connecting it to an assumption or design choice?

5. HONEST REFLECTION (3 marks): Does it include a short and honest reflection about what couldn't be implemented, what surprised them, and what they would revisit with more time?

Additional checks:
- Is the report within ~4 pages (excluding references)?
- Does it synthesize across tasks (not just copy from notebooks)?

Return JSON:
{{
  "paper_summary": {{"score": <0-3>, "reason": "<1-2 sentence justification>"}},
  "reproduction_results": {{"score": <0-3>, "reason": "<justification>"}},
  "ablation_findings": {{"score": <0-3>, "reason": "<justification>"}},
  "failure_mode": {{"score": <0-3>, "reason": "<justification>"}},
  "honest_reflection": {{"score": <0-3>, "reason": "<justification>"}},
  "total_score": <0-15>,
  "overall_reason": "<2-3 sentence overall assessment>"
}}""",
                EVALUATOR_SYSTEM
            )

            total_score = min(15, max(0, eval_report.get("total_score", 0)))

            # Build detailed breakdown
            section_details = {}
            for section in ["paper_summary", "reproduction_results", "ablation_findings", "failure_mode", "honest_reflection"]:
                s = eval_report.get(section, {})
                section_details[section] = {
                    "score": min(3, max(0, s.get("score", 0))),
                    "max": 3,
                    "reason": s.get("reason", ""),
                }

            # Verify total matches sum of sections
            section_sum = sum(s["score"] for s in section_details.values())
            total_score = section_sum  # Use section sum for accuracy

            results["tasks"]["task_4_1"] = {
                "score": total_score,
                "max": 15,
                "reason": eval_report.get("overall_reason", ""),
                "sections": section_details,
                "report_length_chars": len(report_text),
            }
        else:
            # PDF exists but text extraction failed
            results["tasks"]["task_4_1"] = {
                "score": 0,
                "max": 15,
                "reason": "report.pdf found but could not extract text (may be image-based PDF). Flagged for manual review.",
                "status": "NEEDS_MANUAL_REVIEW",
            }
            results["flags"].append("REPORT_TEXT_EXTRACTION_FAILED")
    else:
        results["tasks"]["task_4_1"] = {
            "score": 0,
            "max": 15,
            "reason": "report.pdf not found in partB/",
        }
        results["flags"].append("REPORT_MISSING")

    # --- Task 4.2: LLM Usage Disclosure (15 marks = 10 files x 1.5) ---
    required_jsons = [
        "llm_task_1_1.json", "llm_task_1_2.json", "llm_task_1_3.json",
        "llm_task_2_1.json", "llm_task_2_2.json", "llm_task_2_3.json",
        "llm_task_3_1.json", "llm_task_3_2.json",
        "llm_task_4_1.json", "llm_task_4_2.json",
    ]

    json_scores = 0
    json_details = {}

    for jf in required_jsons:
        content = fetch_file_content(owner, repo, f"partB/{jf}", branch)
        if content:
            try:
                data = json.loads(content)
                # Check required fields
                has_log = "full_llm_interaction_log" in data
                log = data.get("full_llm_interaction_log", [])

                if isinstance(log, list) and len(log) > 0:
                    first = log[0]
                    has_task_tag = "task_tag" in first
                    has_code_verbatim = "code_used_verbatim" in first
                    has_top5 = "top_5_prompts" in data
                    has_declaration = "student_declaration" in data

                    if has_log and has_task_tag:
                        json_scores += 1.5
                        json_details[jf] = "COMPLETE"
                    else:
                        json_scores += 0.75
                        json_details[jf] = "PARTIAL - missing required fields"
                elif isinstance(log, list) and len(log) == 0:
                    # Explicitly states no LLM used
                    if data.get("no_llm_used") or any("no llm" in str(v).lower() for v in data.values()):
                        json_scores += 1.5
                        json_details[jf] = "COMPLETE (no LLM used)"
                    else:
                        json_scores += 0.5
                        json_details[jf] = "EMPTY log without explanation"
                else:
                    json_scores += 0.5
                    json_details[jf] = "INVALID structure"
            except json.JSONDecodeError:
                json_details[jf] = "INVALID JSON"
        else:
            json_details[jf] = "MISSING"

    results["tasks"]["task_4_2"] = {
        "score": round(json_scores, 1),
        "max": 15,
        "file_details": json_details,
        "reason": f"{sum(1 for v in json_details.values() if v.startswith('COMPLETE'))}/10 files complete",
    }

    results["total"] = sum(t.get("score", 0) for t in results["tasks"].values())
    return results


def evaluate_student_part_b(student_b: dict, student_a: dict, ground_truth: dict) -> dict:
    """
    Full Part B evaluation for a single student.
    """
    roll = student_b["roll_number"]
    print(f"\n{'='*60}")
    print(f"Evaluating Part B: {roll} ({student_b['full_name']})")
    print(f"Paper: {student_b['paper_title'][:60]}")
    print(f"{'='*60}")

    owner, repo = parse_github_url(student_b["github_repo"])
    if not owner or not repo:
        return {"roll_number": roll, "error": "Invalid GitHub URL", "final_total": 0}

    from agents.github_checker import check_repo_exists
    repo_info = check_repo_exists(owner, repo)
    branch = repo_info.get("default_branch", "main")

    result = {
        "roll_number": roll,
        "full_name": student_b["full_name"],
        "paper_title": student_b["paper_title"],
        "github_url": student_b["github_repo"],
    }

    # Step 1: Structural validation
    print(f"  Checking repo structure...")
    struct = validate_part_b_repo(student_b["github_repo"], roll)
    result["structure"] = struct
    structure_penalty = struct.get("penalty", 0)

    # Step 2: Q1 - Paper Understanding (25 marks)
    print(f"  Evaluating Q1: Paper Understanding...")
    q1 = evaluate_q1_understanding(owner, repo, branch, ground_truth)
    result["q1"] = q1

    # Step 3: Q2 - Reproduction (40 marks)
    print(f"  Evaluating Q2: Reproduction...")
    q2 = evaluate_q2_reproduction(owner, repo, branch, ground_truth)
    result["q2"] = q2

    # Step 4: Q3 - Ablation Study (35 marks)
    print(f"  Evaluating Q3: Ablation Study...")
    q3 = evaluate_q3_ablation(owner, repo, branch, ground_truth)
    result["q3"] = q3

    # Step 5: Q4 - Report & LLM Usage (30 marks)
    print(f"  Evaluating Q4: Report & LLM Usage...")
    q4 = evaluate_q4_report(owner, repo, branch, ground_truth)
    result["q4"] = q4

    # Aggregate
    raw_total = q1["total"] + q2["total"] + q3["total"] + q4["total"]
    final_total = max(0, raw_total + structure_penalty)  # penalty is negative

    result["raw_total"] = raw_total
    result["structure_penalty"] = structure_penalty
    result["final_total"] = final_total
    result["out_of"] = 130
    result["scaled_score"] = round(final_total / 130 * 30, 2)  # Scaled to 30% of midsem

    all_flags = struct.get("flags", []) + q1.get("flags", []) + q2.get("flags", []) + q3.get("flags", []) + q4.get("flags", [])
    result["flags"] = all_flags
    result["needs_human_review"] = len(all_flags) > 0

    # Print summary
    print(f"\n  SCORES:")
    print(f"    Q1 (Understanding): {q1['total']}/25")
    for t, v in q1.get("tasks", {}).items():
        print(f"      {t}: {v['score']}/{v['max']}")
    print(f"    Q2 (Reproduction): {q2['total']}/40")
    for t, v in q2.get("tasks", {}).items():
        print(f"      {t}: {v['score']}/{v['max']}")
    print(f"    Q3 (Ablation): {q3['total']}/35")
    for t, v in q3.get("tasks", {}).items():
        print(f"      {t}: {v['score']}/{v['max']}")
    print(f"    Q4 (Report/LLM): {q4['total']}/30")
    for t, v in q4.get("tasks", {}).items():
        print(f"      {t}: {v.get('score', 0)}/{v['max']}")
    if structure_penalty:
        print(f"    Structure Penalty: {structure_penalty}")
    print(f"  FINAL: {final_total}/130 (scaled: {result['scaled_score']}/30)")
    if all_flags:
        print(f"  FLAGS ({len(all_flags)}): {all_flags[:5]}...")

    # Save
    score_path = SCORES_DIR / f"{roll}_part_b.json"
    with open(score_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    return result


def run_all_part_b():
    """Run Part B evaluation for all Part B submissions."""
    summary_path = OUTPUT_DIR / "phase0_summary.json"
    with open(summary_path) as f:
        summary = json.load(f)

    part_b_students = summary["part_b_students"]
    valid_a = {s["roll_number"]: s for s in summary["valid_students"]}

    # Deduplicate Part B submissions (keep latest per student)
    by_roll = {}
    for s in part_b_students:
        roll = s["roll_number"]
        by_roll[roll] = s  # Last one wins since they're in order

    print(f"Starting Part B evaluation for {len(by_roll)} students...")

    all_results = []
    for roll, student_b in by_roll.items():
        student_a = valid_a.get(roll, {})
        if not student_a:
            print(f"\n  WARNING: {roll} has Part B but no valid Part A - skipping")
            continue

        # Get ground truth
        safe_title = student_a["paper_title"][:60].replace("/", "_").replace(" ", "_")
        gt_path = GROUND_TRUTH_DIR / f"{safe_title}.json"

        if gt_path.exists():
            with open(gt_path) as f:
                ground_truth = json.load(f)
        else:
            print(f"  Generating ground truth for: {student_a['paper_title'][:50]}")
            from agents.paper_ground_truth import generate_ground_truth as gen_gt
            ground_truth = gen_gt(
                title=student_a["paper_title"],
                venue=student_a["venue"],
                year=student_a.get("year_of_publication", 0),
                method=student_a["primary_method"],
                url=student_a.get("paper_link", ""),
            )
            if ground_truth:
                GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
                with open(gt_path, "w") as f:
                    json.dump(ground_truth, f, indent=2)

        result = evaluate_student_part_b(student_b, student_a, ground_truth or {})
        all_results.append(result)
        time.sleep(1)

    # Save all
    all_path = OUTPUT_DIR / "part_b_all_results.json"
    with open(all_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n{'='*70}")
    print(f"PART B EVALUATION COMPLETE")
    print(f"{'='*70}")
    for r in all_results:
        print(f"  {r['roll_number']}: {r.get('final_total', 0)}/130 (scaled: {r.get('scaled_score', 0)}/30)")

    return all_results


if __name__ == "__main__":
    os.chdir(str(Path(__file__).parent.parent))
    run_all_part_b()
