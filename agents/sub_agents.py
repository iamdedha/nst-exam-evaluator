"""
Sub-Agent Evaluators for High-Stakes Tasks

Focused, single-dimension LLM agents for:
- Task 2.2 (Implementation - 20 marks): annotation, citation, depth
- Task 3.1 (Ablation - 20 marks): execution, interpretation
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agents.llm_client import call_llm_json

EVALUATOR_SYSTEM = """You are an expert ML exam evaluator for a BTech 3rd year Advanced Machine Learning course.
You evaluate ONE specific dimension of a student's submission. Be fair, consistent, and strict.
Grade based on specificity to the paper (not generic ML knowledge)."""


# ---------------------------------------------------------------------------
# Task 2.2 Sub-Agents (Implementation - 20 marks total)
# ---------------------------------------------------------------------------

def annotation_agent(notebook_text: str, ground_truth: dict) -> dict:
    """Check if each significant code block has a following markdown explanation. (7 marks)"""
    result = call_llm_json(
        f"""You are evaluating ONLY whether code blocks have markdown explanations.

STUDENT'S NOTEBOOK (code + markdown cells):
{notebook_text[:6000]}

EVALUATE (0-7 marks):
- Count how many significant code blocks exist (imports/boilerplate don't count).
- For each significant code block, check if a markdown cell follows it explaining what it does in 2-3 sentences.
- 7 marks: Every significant block has a clear explanation.
- 4-6 marks: Most blocks have explanations but some are missing or too brief.
- 1-3 marks: Few blocks have explanations.
- 0 marks: No markdown explanations at all, or notebook is empty.

Return ONLY this JSON:
{{
  "score": <0-7>,
  "reasoning": "<2-3 sentences explaining your evaluation>",
  "evidence": ["<quote or reference to a specific well-explained block>", "<quote or reference to a block missing explanation>"],
  "total_code_blocks": <int>,
  "blocks_with_explanation": <int>,
  "confidence": "high"|"medium"|"low"
}}""",
        EVALUATOR_SYSTEM
    )

    return {
        "score": min(7, max(0, result.get("score", 0))),
        "max": 7,
        "reasoning": result.get("reasoning", "Evaluation failed"),
        "evidence": result.get("evidence", []),
        "confidence": result.get("confidence", "low"),
        "dimension": "Code-to-Markdown Annotations",
    }


def citation_agent(notebook_text: str, ground_truth: dict) -> dict:
    """Check if markdown explanations cite specific equations/sections from the paper. (6 marks)"""
    gt_context = json.dumps({
        "algorithm_steps": ground_truth.get("algorithm_steps", []),
        "key_equations": ground_truth.get("key_equations", []),
    }, indent=2)

    result = call_llm_json(
        f"""You are evaluating ONLY whether the student's markdown cells cite specific parts of the paper.

PAPER'S KNOWN EQUATIONS AND ALGORITHM STEPS:
{gt_context}

STUDENT'S NOTEBOOK:
{notebook_text[:6000]}

EVALUATE (0-6 marks):
- Do markdown explanations reference specific equation numbers, section numbers, figure numbers, or algorithm step names from the paper?
- 5-6 marks: Multiple specific references (e.g., "Eq. 3", "Section 4.1", "Algorithm 2, Step 3").
- 3-4 marks: Some references but many are vague (e.g., "as described in the paper").
- 1-2 marks: Rarely references the paper specifically.
- 0 marks: No paper references at all.

Return ONLY this JSON:
{{
  "score": <0-6>,
  "reasoning": "<2-3 sentences>",
  "evidence": ["<example of a good citation>", "<example of a missing or vague citation>"],
  "citations_found": <int>,
  "confidence": "high"|"medium"|"low"
}}""",
        EVALUATOR_SYSTEM
    )

    return {
        "score": min(6, max(0, result.get("score", 0))),
        "max": 6,
        "reasoning": result.get("reasoning", "Evaluation failed"),
        "evidence": result.get("evidence", []),
        "confidence": result.get("confidence", "low"),
        "dimension": "Paper Citation Quality",
    }


def depth_agent(notebook_text: str, ground_truth: dict) -> dict:
    """Check implementation depth: from-scratch vs library import, algorithm coverage. (7 marks)"""
    gt_context = json.dumps({
        "algorithm_steps": ground_truth.get("algorithm_steps", []),
        "method_category": ground_truth.get("method_category", ""),
        "core_contribution": ground_truth.get("core_contribution", ""),
    }, indent=2)

    result = call_llm_json(
        f"""You are evaluating ONLY the depth and originality of the implementation.

PAPER'S CORE METHOD AND ALGORITHM STEPS:
{gt_context}

STUDENT'S NOTEBOOK:
{notebook_text[:6000]}

EVALUATE (0-7 marks):
- Is the core method implemented from scratch, or does the student just call sklearn/library functions?
- Are the key algorithm steps from the paper clearly visible in the code?
- A from-scratch implementation that covers most steps scores high even if results are imperfect.
- A notebook that just imports sklearn.SomeModel, calls .fit(), and shows results scores low.

Scoring:
- 6-7: From-scratch or heavily customized implementation covering most algorithm steps.
- 4-5: Partial from-scratch with some library usage, several steps covered.
- 2-3: Mostly library calls but with some customization or step-by-step explanation.
- 0-1: Pure library import with no implementation of the paper's specific method.

Return ONLY this JSON:
{{
  "score": <0-7>,
  "reasoning": "<2-3 sentences>",
  "evidence": ["<specific code pattern showing depth or lack thereof>"],
  "is_from_scratch": true|false,
  "steps_covered": <int>,
  "total_expected_steps": <int>,
  "confidence": "high"|"medium"|"low"
}}""",
        EVALUATOR_SYSTEM
    )

    return {
        "score": min(7, max(0, result.get("score", 0))),
        "max": 7,
        "reasoning": result.get("reasoning", "Evaluation failed"),
        "evidence": result.get("evidence", []),
        "confidence": result.get("confidence", "low"),
        "dimension": "Implementation Depth",
    }


# ---------------------------------------------------------------------------
# Task 3.1 Sub-Agents (Ablation Study - 20 marks total)
# ---------------------------------------------------------------------------

def execution_agent(notebook_text: str, ground_truth: dict) -> dict:
    """Check ablation execution: code runs, produces comparison, independent ablations. (8 marks)"""
    gt_context = json.dumps({
        "key_components_for_ablation": ground_truth.get("key_components_for_ablation", []),
    }, indent=2)

    result = call_llm_json(
        f"""You are evaluating ONLY the execution quality of the ablation study.

VALID COMPONENTS TO ABLATE (from the paper):
{gt_context}

STUDENT'S NOTEBOOK:
{notebook_text[:6000]}

EVALUATE (0-8 marks):
- Did the student ablate exactly TWO distinct components?
- Are the components actually part of the paper's method (not random hyperparameters)?
- Is each ablation independent (one component removed at a time, not both)?
- Is there a comparison plot or table showing full method vs each ablated version?
- Do code cells have outputs (evidence the code actually ran)?

Scoring:
- 7-8: Two valid, independent ablations with clear comparison output.
- 5-6: Two ablations but one component is questionable or comparison is weak.
- 3-4: Only one ablation, or components are not from the paper's method.
- 0-2: No proper ablation or notebook is empty/not executed.

Return ONLY this JSON:
{{
  "score": <0-8>,
  "reasoning": "<2-3 sentences>",
  "evidence": ["<what was ablated>", "<comparison format used>"],
  "num_ablations": <int>,
  "components_valid": true|false,
  "has_comparison_output": true|false,
  "confidence": "high"|"medium"|"low"
}}""",
        EVALUATOR_SYSTEM
    )

    return {
        "score": min(8, max(0, result.get("score", 0))),
        "max": 8,
        "reasoning": result.get("reasoning", "Evaluation failed"),
        "evidence": result.get("evidence", []),
        "confidence": result.get("confidence", "low"),
        "dimension": "Ablation Execution",
    }


def interpretation_agent(notebook_text: str, ground_truth: dict) -> dict:
    """Check ablation interpretation: reasoning quality, impact discussion. (12 marks)"""
    gt_context = json.dumps({
        "key_components_for_ablation": ground_truth.get("key_components_for_ablation", []),
        "key_assumptions": ground_truth.get("key_assumptions", []),
    }, indent=2)

    result = call_llm_json(
        f"""You are evaluating ONLY the quality of interpretation in the ablation study.

PAPER'S COMPONENTS AND ASSUMPTIONS:
{gt_context}

STUDENT'S NOTEBOOK:
{notebook_text[:6000]}

EVALUATE (0-12 marks, 6 per ablation):
For each of the two ablations, check:
- Is there a 5-7 sentence interpretation paragraph?
- Does it discuss whether removing the component hurt or improved performance?
- Does it explain WHY the removal had that effect (connecting to the method's design)?
- Is the reasoning specific to this paper (not generic "removing features hurts performance")?

Scoring per ablation (6 marks each, 12 total):
- 5-6: Thoughtful, paper-specific reasoning explaining the mechanism.
- 3-4: Reasonable interpretation but partly generic.
- 1-2: Brief or superficial interpretation.
- 0: No interpretation provided.

Return ONLY this JSON:
{{
  "score": <0-12>,
  "reasoning": "<2-3 sentences overall assessment>",
  "evidence": ["<example of good reasoning>", "<example of weak or missing reasoning>"],
  "ablation_1_interpretation_quality": "strong"|"moderate"|"weak"|"missing",
  "ablation_2_interpretation_quality": "strong"|"moderate"|"weak"|"missing",
  "confidence": "high"|"medium"|"low"
}}""",
        EVALUATOR_SYSTEM
    )

    return {
        "score": min(12, max(0, result.get("score", 0))),
        "max": 12,
        "reasoning": result.get("reasoning", "Evaluation failed"),
        "evidence": result.get("evidence", []),
        "confidence": result.get("confidence", "low"),
        "dimension": "Ablation Interpretation",
    }
