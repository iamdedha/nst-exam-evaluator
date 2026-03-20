"""
Paper Ground Truth Agent: Analyzes a research paper and produces
a structured ground truth document for evaluation.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agents.llm_client import call_llm_json
from agents.paper_fetcher import fetch_paper_text

GROUND_TRUTH_DIR = Path(__file__).parent.parent.parent / "evaluator" / "output" / "ground_truths"
GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = """You are an expert machine learning researcher and exam evaluator.
You are analyzing a classical ML research paper to create a ground truth evaluation document.
This document will be used to evaluate student submissions who selected this paper for their exam.

Be thorough, accurate, and specific to THIS paper (not generic descriptions of the method family).
If the paper text is partial or you cannot determine something, say "UNABLE_TO_DETERMINE" for that field."""

ANALYSIS_PROMPT_TEMPLATE = """Analyze the following research paper and produce a structured JSON ground truth document.

**Paper Title:** {title}
**Stated Venue:** {venue}
**Stated Year:** {year}
**Stated Method Category:** {method}
**Paper URL:** {url}

**Paper Content:**
{paper_text}

---

Produce a JSON object with EXACTLY these fields:

{{
  "paper_title": "<exact title>",
  "venue": "<venue name>",
  "venue_abbreviation": "<e.g. KDD, ICML, NeurIPS>",
  "year": <integer>,
  "venue_is_core_a_star": <true/false - is this a CORE A* venue?>,
  "year_in_range": <true/false - is year between 2009-2012?>,

  "method_category": "<ARIMA|GMM|SVM|TIME_SERIES|KERNEL|OTHER>",
  "method_category_valid": <true/false - aligns with ARIMA/GMM/SVM or close variants?>,
  "is_methodological": <true/false - is the primary contribution a method/algorithm?>,
  "is_dataset_benchmark_system_paper": <true/false>,
  "is_deep_learning": <true/false>,
  "is_survey": <true/false>,

  "core_contribution": "<2-3 sentence summary of the SPECIFIC method proposed>",
  "algorithm_steps": [
    "<Step 1: specific description>",
    "<Step 2: ...>",
    "..."
  ],
  "key_equations": [
    "<Eq/Section reference: brief description of what it computes>"
  ],

  "key_assumptions": [
    {{
      "assumption": "<specific assumption the method makes>",
      "why_needed": "<why the method depends on this>",
      "violation_scenario": "<when/how this assumption breaks>"
    }}
  ],

  "baselines_compared": ["<method1>", "<method2>", "..."],
  "baseline_limitations_identified": "<what limitation of baselines does this paper claim to address>",
  "proposed_improvement": "<how does the method attempt to overcome the baseline limitation>",
  "condition_where_baseline_wins": "<a realistic scenario where the proposed method would NOT outperform baselines>",

  "datasets_used": ["<dataset1>", "<dataset2>"],
  "dataset_publicly_available": <true/false>,
  "suitable_toy_datasets": ["<toy dataset that would work for reproducing this method>", "..."],
  "toy_dataset_justification": "<why these toy datasets are appropriate>",

  "compute_requirements": "<CPU_FEASIBLE|GPU_PREFERRED|GPU_REQUIRED>",
  "reproducibility_assessment": "<EASY|MODERATE|HARD>",
  "reproducibility_notes": "<any specific challenges for reproduction>",

  "key_components_for_ablation": [
    {{
      "component": "<name of a removable/simplifiable component>",
      "role_in_method": "<what it does in the full method>",
      "expected_effect_of_removal": "<what would happen if removed>"
    }}
  ],

  "known_failure_modes": [
    {{
      "scenario": "<when the method fails>",
      "reason": "<why it fails - linked to an assumption>",
      "related_assumption": "<which assumption is violated>"
    }}
  ],

  "paper_quality_flags": {{
    "has_clear_algorithm": <true/false>,
    "has_experimental_results": <true/false>,
    "has_comparison_with_baselines": <true/false>,
    "code_available": <true/false or "UNKNOWN">
  }}
}}

Return ONLY the JSON, no other text."""


def generate_ground_truth(
    title: str,
    venue: str,
    year: int,
    method: str,
    url: str,
    paper_text: str = None,
) -> dict:
    """
    Generate a ground truth document for a single paper.
    If paper_text is not provided, attempts to fetch it.
    """
    # Fetch paper if needed
    if not paper_text:
        print(f"  Fetching paper: {title[:60]}...")
        fetch_result = fetch_paper_text(url, title)
        if fetch_result["status"] == "success":
            paper_text = fetch_result["text"]
        else:
            print(f"  WARNING: Could not fetch paper. Error: {fetch_result.get('error', 'unknown')}")
            paper_text = f"[PAPER TEXT UNAVAILABLE - Evaluate based on title, venue, and method only]\nTitle: {title}\nVenue: {venue}\nYear: {year}\nMethod: {method}"

    # Truncate if too long (keep first ~15k chars to stay within context)
    if len(paper_text) > 15000:
        paper_text = paper_text[:15000] + "\n\n[TEXT TRUNCATED - paper continues...]"

    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        title=title,
        venue=venue,
        year=year,
        method=method,
        url=url,
        paper_text=paper_text,
    )

    print(f"  Calling LLM for ground truth analysis...")
    result = call_llm_json(prompt, SYSTEM_PROMPT)

    if "_raw_response" in result:
        print(f"  WARNING: LLM returned non-JSON response")
        result["_parse_error"] = True

    # Add metadata
    result["_metadata"] = {
        "paper_url": url,
        "paper_text_length": len(paper_text) if paper_text else 0,
        "paper_text_available": bool(paper_text and len(paper_text) > 100),
    }

    return result


def process_all_papers(phase0_summary_path: str):
    """
    Process all unique papers from Phase 0 summary.
    Generates ground truth for each.
    """
    with open(phase0_summary_path) as f:
        summary = json.load(f)

    valid_students = summary["valid_students"]

    # Group by paper title to avoid duplicate analysis
    papers = {}
    for student in valid_students:
        title = student["paper_title"]
        if title not in papers:
            papers[title] = {
                "title": title,
                "venue": student["venue"],
                "year": student["year_of_publication"],
                "method": student["primary_method"],
                "url": student["paper_link"],
                "students": [],
            }
        papers[title]["students"].append(student["roll_number"])

    print(f"Processing {len(papers)} unique papers...")
    print("=" * 70)

    results = {}
    failed = []

    for i, (title, info) in enumerate(papers.items()):
        print(f"\n[{i+1}/{len(papers)}] {title[:70]}...")
        print(f"  Venue: {info['venue']}, Year: {info['year']}, Method: {info['method']}")
        print(f"  URL: {info['url'][:80]}")
        print(f"  Students: {info['students']}")

        # Check cache
        safe_title = title[:60].replace("/", "_").replace(" ", "_")
        cache_path = GROUND_TRUTH_DIR / f"{safe_title}.json"
        if cache_path.exists():
            print(f"  Using cached ground truth")
            with open(cache_path) as f:
                gt = json.load(f)
            results[title] = gt
            continue

        gt = generate_ground_truth(
            title=info["title"],
            venue=info["venue"],
            year=info["year"],
            method=info["method"],
            url=info["url"],
        )

        if gt and "_parse_error" not in gt:
            results[title] = gt
            # Cache it
            with open(cache_path, "w") as f:
                json.dump(gt, f, indent=2)
            print(f"  Ground truth generated and cached")
        else:
            failed.append({
                "title": title,
                "url": info["url"],
                "error": gt.get("_raw_response", "Unknown error")[:200] if gt else "Empty response",
            })
            print(f"  FAILED to generate ground truth")

        # Small delay to avoid rate limiting
        import time
        time.sleep(1)

    # Save summary of all ground truths
    gt_summary = {
        "total_papers": len(papers),
        "successful": len(results),
        "failed": len(failed),
        "failed_papers": failed,
    }

    summary_path = GROUND_TRUTH_DIR / "_summary.json"
    with open(summary_path, "w") as f:
        json.dump(gt_summary, f, indent=2)

    print(f"\n{'=' * 70}")
    print(f"Ground Truth Generation Complete:")
    print(f"  Successful: {len(results)}/{len(papers)}")
    print(f"  Failed: {len(failed)}")
    if failed:
        print(f"\n  Papers requiring manual upload:")
        for f_info in failed:
            print(f"    - {f_info['title'][:60]}: {f_info['error'][:100]}")

    return results, failed


if __name__ == "__main__":
    os.chdir(str(Path(__file__).parent.parent))
    summary_path = Path(__file__).parent.parent.parent / "evaluator" / "output" / "phase0_summary.json"
    process_all_papers(str(summary_path))
