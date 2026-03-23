"""
GitHub Repository Checker: Validates repo existence, structure, and fetches files.
"""

import json
import os
import re
import time
import requests
from pathlib import Path
from urllib.parse import urlparse

HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "NST-Exam-Evaluator",
}

# If you have a GitHub token, set it here for higher rate limits
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract owner/repo from GitHub URL."""
    url = url.strip().rstrip("/")
    # Remove .git suffix
    if url.endswith(".git"):
        url = url[:-4]
    # Remove /tree/main etc
    url = re.sub(r'/tree/.*$', '', url)

    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "", ""


def check_repo_exists(owner: str, repo: str, retries: int = 3) -> dict:
    """Check if a GitHub repo exists and is public. Retries on rate limiting."""
    for attempt in range(retries):
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=HEADERS,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "exists": True,
                    "is_public": not data.get("private", True),
                    "default_branch": data.get("default_branch", "main"),
                    "description": data.get("description", ""),
                }
            elif resp.status_code == 404:
                return {"exists": False, "error": "Repository not found"}
            elif resp.status_code in (403, 429):
                # Rate limited - wait and retry
                wait_time = min(2 ** attempt * 5, 60)
                print(f"    GitHub rate limited ({resp.status_code}), waiting {wait_time}s (attempt {attempt+1}/{retries})...")
                time.sleep(wait_time)
                continue
            else:
                return {"exists": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return {"exists": False, "error": str(e)}
    return {"exists": False, "error": "Rate limited after retries"}


def check_file_exists(owner: str, repo: str, path: str, branch: str = "main") -> dict:
    """Check if a specific file exists in the repo."""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            headers=HEADERS,
            params={"ref": branch},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "exists": True,
                "size": data.get("size", 0),
                "type": data.get("type", ""),
                "download_url": data.get("download_url", ""),
            }
        else:
            return {"exists": False}
    except Exception:
        return {"exists": False}


def fetch_file_content(owner: str, repo: str, path: str, branch: str = "main") -> str:
    """Fetch raw content of a file from GitHub."""
    try:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        resp = requests.get(url, headers={"User-Agent": "NST-Exam-Evaluator"}, timeout=15)
        if resp.status_code == 200:
            return resp.text
        return ""
    except Exception:
        return ""


def list_directory(owner: str, repo: str, path: str = "", branch: str = "main") -> list:
    """List files in a directory of the repo."""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            headers=HEADERS,
            params={"ref": branch},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return [{"name": f["name"], "type": f["type"], "size": f.get("size", 0)} for f in data]
        return []
    except Exception:
        return []


def validate_part_a_repo(github_url: str, roll_number: str) -> dict:
    """
    Validate Part A repository requirements:
    - Repo exists and is public
    - Repo naming: rollnumber-midsem
    - llm_usage_partA.json exists at root
    - JSON is valid and follows required schema
    """
    owner, repo = parse_github_url(github_url)
    result = {
        "github_url": github_url,
        "owner": owner,
        "repo": repo,
        "checks": {},
        "score_adjustments": {},
        "flags": [],
    }

    if not owner or not repo:
        result["checks"]["url_valid"] = False
        result["flags"].append("INVALID_GITHUB_URL")
        return result

    result["checks"]["url_valid"] = True

    # Check repo exists
    repo_info = check_repo_exists(owner, repo)
    result["checks"]["repo_exists"] = repo_info.get("exists", False)
    result["checks"]["repo_public"] = repo_info.get("is_public", False)
    branch = repo_info.get("default_branch", "main")

    if not repo_info.get("exists"):
        return result

    # Check naming convention (record but don't flag)
    expected_name = f"{roll_number}-midsem"
    result["checks"]["naming_correct"] = repo.lower() == expected_name.lower()

    # Check llm_usage_partA.json - search multiple locations
    llm_json_candidates = [
        "llm_usage_partA.json",
        "LLM_usage_partA.json",
        "llm_usage.json",
        "partA/llm_usage_partA.json",
        "partA/llm_usage_log.json",
        "partA/LLM_usage_partA.json",
    ]

    json_content = None
    json_found_path = None
    for candidate in llm_json_candidates:
        content = fetch_file_content(owner, repo, candidate, branch)
        if content:
            json_content = content
            json_found_path = candidate
            break

    result["checks"]["llm_json_exists"] = json_content is not None
    result["checks"]["llm_json_path"] = json_found_path or ""

    if json_content:
        try:
            data = json.loads(json_content)
            result["checks"]["llm_json_valid"] = True
            result["llm_json_data"] = data

            # Schema validation
            schema_checks = validate_llm_json_schema(data)
            result["checks"]["llm_json_schema"] = schema_checks
        except json.JSONDecodeError:
            result["checks"]["llm_json_valid"] = False
    else:
        result["checks"]["llm_json_valid"] = False

    return result


def validate_llm_json_schema(data: dict) -> dict:
    """Validate the LLM usage JSON against required schema."""
    checks = {
        "has_student_metadata": "student_metadata" in data,
        "has_llm_tools_used": "llm_tools_used" in data,
        "has_interaction_log": "full_llm_interaction_log" in data,
        "has_top_5_prompts": "top_5_prompts" in data,
        "has_student_declaration": "student_declaration" in data,
    }

    # Detailed checks
    if checks["has_student_metadata"]:
        meta = data["student_metadata"]
        checks["metadata_has_name"] = "name" in meta
        checks["metadata_has_roll"] = "roll_number" in meta
        checks["metadata_has_date"] = "submission_date" in meta

    if checks["has_interaction_log"]:
        log = data["full_llm_interaction_log"]
        checks["interaction_log_count"] = len(log) if isinstance(log, list) else 0
        if isinstance(log, list) and len(log) > 0:
            first = log[0]
            checks["log_has_required_fields"] = all(
                k in first for k in ["interaction_id", "tool_name", "purpose", "prompt"]
            )

    if checks["has_top_5_prompts"]:
        prompts = data["top_5_prompts"]
        checks["top_5_count"] = len(prompts) if isinstance(prompts, list) else 0
        checks["top_5_has_5"] = checks["top_5_count"] == 5

    if checks["has_student_declaration"]:
        decl = data["student_declaration"]
        checks["declaration_has_statement"] = "statement" in decl
        checks["declaration_acknowledged"] = decl.get("understanding_acknowledged", False)

    return checks


def validate_part_b_repo(github_url: str, roll_number: str) -> dict:
    """
    Validate Part B repository requirements:
    - partB/ folder exists
    - Required notebooks exist with outputs
    - report.pdf exists
    - requirements.txt exists
    - data/ folder with README
    - results/ folder with images
    - 10 LLM JSON files exist
    """
    owner, repo = parse_github_url(github_url)
    result = {
        "github_url": github_url,
        "owner": owner,
        "repo": repo,
        "checks": {},
        "flags": [],
        "penalty": 0,
    }

    if not owner or not repo:
        result["flags"].append("INVALID_GITHUB_URL")
        return result

    repo_info = check_repo_exists(owner, repo)
    if not repo_info.get("exists"):
        result["flags"].append("REPO_NOT_FOUND")
        # Don't return early - try to check files anyway using default branch
        branch = "main"
    else:
        branch = repo_info.get("default_branch", "main")

    # Check partB/ directory (try multiple folder name variants)
    partb_folder = "partB"
    partb_contents = []
    for candidate in ["partB", "part-B", "Part_B", "Part-B", "part_B", "PartB", "part_b", "PARTB", "part-b"]:
        partb_contents = list_directory(owner, repo, candidate, branch)
        if partb_contents:
            partb_folder = candidate
            break

    result["checks"]["partb_folder_exists"] = len(partb_contents) > 0
    result["partb_folder"] = partb_folder

    if not partb_contents:
        result["flags"].append("PARTB_FOLDER_MISSING")
        result["penalty"] = -20
        return result

    partb_files = {f["name"]: f for f in partb_contents}

    # Required notebooks (with flexible naming)
    required_notebooks = [
        "task_1_1.ipynb", "task_1_2.ipynb", "task_1_3.ipynb",
        "task_2_1.ipynb", "task_2_2.ipynb", "task_2_3.ipynb",
        "task_3_1.ipynb", "task_3_2.ipynb",
    ]

    def find_notebook(expected_name, files_dict):
        """Find notebook with flexible naming: task_1_1, task1_1, etc."""
        if expected_name in files_dict:
            return expected_name
        # Try without underscore between 'task' and number
        alt = expected_name.replace("task_", "task")
        if alt in files_dict:
            return alt
        # Try case-insensitive
        for fname in files_dict:
            if fname.lower() == expected_name.lower() or fname.lower() == alt.lower():
                return fname
        # Fuzzy: extract number part and match
        num_part = expected_name.replace("task_", "").replace(".ipynb", "").replace("_", "")
        for fname in files_dict:
            if fname.endswith(".ipynb") and num_part in fname.replace("_", ""):
                return fname
        return None

    found_notebooks = []
    missing_notebooks = []
    for nb in required_notebooks:
        match = find_notebook(nb, partb_files)
        if match:
            found_notebooks.append(nb)
        else:
            missing_notebooks.append(nb)

    result["checks"]["notebooks_found"] = found_notebooks
    result["checks"]["notebooks_missing"] = missing_notebooks

    # report.pdf (case-insensitive)
    # Report: check for PDF, MD, or any file with "report" in name
    report_found = any("report" in f.lower() and (f.lower().endswith(".pdf") or f.lower().endswith(".md") or f.lower().endswith(".docx")) for f in partb_files)
    result["checks"]["report_exists"] = report_found
    result["checks"]["report_filename"] = next((f for f in partb_files if "report" in f.lower()), None)

    # requirements.txt (check partB/ and root)
    req_in_partb = "requirements.txt" in partb_files
    root_files = list_directory(owner, repo, "", branch)
    req_at_root = any(f["name"] == "requirements.txt" for f in root_files)
    result["checks"]["requirements_exists"] = req_in_partb or req_at_root

    # data/ folder
    data_contents = list_directory(owner, repo, f"{partb_folder}/data", branch)
    result["checks"]["data_folder_exists"] = len(data_contents) > 0
    if data_contents:
        result["checks"]["data_has_readme"] = any(
            f["name"].lower().startswith("readme") for f in data_contents
        )

    # results/ folder
    results_contents = list_directory(owner, repo, f"{partb_folder}/results", branch)
    if not results_contents:
        # Try "result" (singular) — some students use that
        results_contents = list_directory(owner, repo, f"{partb_folder}/result", branch)
    result["checks"]["results_folder_exists"] = len(results_contents) > 0
    result["checks"]["results_files"] = [f["name"] for f in results_contents]

    # LLM JSON files — check per-task files OR consolidated file
    required_llm_jsons = [
        "llm_task_1_1.json", "llm_task_1_2.json", "llm_task_1_3.json",
        "llm_task_2_1.json", "llm_task_2_2.json", "llm_task_2_3.json",
        "llm_task_3_1.json", "llm_task_3_2.json",
        "llm_task_4_1.json", "llm_task_4_2.json",
    ]

    # Check for consolidated llm_usage_partB.json at root or in partB/
    has_consolidated_llm = any(f["name"].lower() in ("llm_usage_partb.json", "llm_usage_part_b.json") for f in root_files)
    if not has_consolidated_llm:
        has_consolidated_llm = any(f.lower() in ("llm_usage_partb.json", "llm_usage_part_b.json") for f in partb_files)

    found_jsons = []
    missing_jsons = []
    if has_consolidated_llm:
        found_jsons = required_llm_jsons  # Treat as all found
        missing_jsons = []
    else:
        for jf in required_llm_jsons:
            if jf in partb_files:
                found_jsons.append(jf)
            else:
                missing_jsons.append(jf)

    result["checks"]["llm_jsons_found"] = found_jsons
    result["checks"]["llm_jsons_missing"] = missing_jsons
    result["checks"]["llm_jsons_score"] = len(found_jsons) * 1.5
    result["checks"]["has_consolidated_llm"] = has_consolidated_llm

    # Check for structural violations
    if missing_notebooks:
        result["flags"].append(f"MISSING_NOTEBOOKS: {missing_notebooks}")
    if not report_found:
        result["flags"].append("REPORT_MISSING")
    if not result["checks"]["requirements_exists"]:
        result["flags"].append("REQUIREMENTS_MISSING")
    if missing_jsons and not has_consolidated_llm:
        result["flags"].append(f"MISSING_LLM_JSONS: {missing_jsons}")

    # Notebook output check - fetch each notebook and check outputs
    for nb_name in found_notebooks:
        nb_content = fetch_file_content(owner, repo, f"{partb_folder}/{nb_name}", branch)
        if nb_content:
            try:
                nb_data = json.loads(nb_content)
                cells = nb_data.get("cells", [])
                code_cells = [c for c in cells if c.get("cell_type") == "code"]
                cells_with_output = [c for c in code_cells if c.get("outputs") and len(c["outputs"]) > 0]
                result["checks"][f"{nb_name}_outputs"] = {
                    "total_code_cells": len(code_cells),
                    "cells_with_output": len(cells_with_output),
                    "has_outputs": len(cells_with_output) > 0,
                }
                if len(cells_with_output) == 0 and len(code_cells) > 0:
                    result["flags"].append(f"NO_OUTPUTS: {nb_name}")
            except json.JSONDecodeError:
                result["flags"].append(f"NOTEBOOK_PARSE_ERROR: {nb_name}")

    return result


if __name__ == "__main__":
    # Test with a sample repo
    result = validate_part_a_repo(
        "https://github.com/Aryan2vb/230049_midsem",
        "230049"
    )
    print(json.dumps(result, indent=2, default=str)[:2000])
