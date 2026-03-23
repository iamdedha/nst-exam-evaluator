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


def fetch_repo_tree(owner: str, repo: str, branch: str = "main", retries: int = 3) -> list | None:
    """
    Fetch the full recursive file tree of a repo in a single API call.
    Returns a list of all file/directory paths, or None on failure.
    """
    for attempt in range(retries):
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}",
                headers=HEADERS,
                params={"recursive": "1"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("truncated"):
                    print(f"    Warning: repo tree truncated (too many files), using fallback")
                    return None
                tree = data.get("tree", [])
                return [{"path": item["path"], "type": item["type"]} for item in tree]
            elif resp.status_code in (403, 429):
                wait = (2 ** attempt) * 5
                print(f"    GitHub rate limited ({resp.status_code}), waiting {wait}s...")
                import time
                time.sleep(wait)
                continue
            else:
                return None
        except Exception as e:
            if attempt < retries - 1:
                continue
            return None
    return None


def build_file_map(tree_items: list) -> dict:
    """
    Build a structured file map from the repo tree using regex matching.
    No hardcoded paths — all discovery is pattern-based.
    """
    import re

    file_map = {
        "partb_folder": None,
        "parta_folder": None,
        "notebooks": {},
        "report": None,
        "llm_json_parta": None,
        "llm_jsons_partb": [],
        "has_consolidated_llm_b": False,
        "requirements": None,
        "data_folder": None,
        "data_readme": None,
        "results_folder": None,
        "results_files": [],
        "all_files": [],
    }

    # Separate files and directories
    all_paths = []
    dirs = set()
    for item in tree_items:
        all_paths.append(item["path"])
        if item["type"] == "tree":
            dirs.add(item["path"])

    file_map["all_files"] = all_paths

    # 1. Find Part B folder (top-level directory matching part?b, case-insensitive)
    for d in dirs:
        # Only top-level dirs (no / in path)
        if "/" not in d and re.match(r'^part[_\-]?b$', d, re.IGNORECASE):
            file_map["partb_folder"] = d
            break

    # 2. Find Part A folder
    for d in dirs:
        if "/" not in d and re.match(r'^part[_\-]?a$', d, re.IGNORECASE):
            file_map["parta_folder"] = d
            break

    partb = file_map["partb_folder"]

    # 3. Find notebooks inside partb_folder
    if partb:
        for path in all_paths:
            if not path.startswith(partb + "/"):
                continue
            # Only direct children (not in subdirectories)
            rel = path[len(partb) + 1:]
            if "/" in rel:
                continue
            if not rel.lower().endswith(".ipynb"):
                continue

            # Extract task number: task_1_1, task1_1, Task_1_1, task 1.1, etc.
            basename = rel.rsplit(".", 1)[0]  # Remove .ipynb
            digits = re.findall(r'\d', basename)
            if len(digits) >= 2:
                canonical = f"task_{digits[0]}_{digits[1]}"
                # Prefer exact match over fuzzy
                if canonical not in file_map["notebooks"] or basename.lower() == canonical:
                    file_map["notebooks"][canonical] = path

    # 4. Find report inside partb_folder
    if partb:
        for path in all_paths:
            if not path.startswith(partb + "/"):
                continue
            rel = path[len(partb) + 1:]
            if "/" in rel:
                continue
            fname = rel.lower()
            if "report" in fname and (fname.endswith(".pdf") or fname.endswith(".md") or fname.endswith(".docx")):
                file_map["report"] = path
                break

    # 5. Find llm_usage_partA.json anywhere
    for path in all_paths:
        fname = path.split("/")[-1].lower()
        if re.match(r'llm.*usage.*part.?a.*\.json', fname, re.IGNORECASE):
            file_map["llm_json_parta"] = path
            break

    # 6. Find Part B LLM JSONs
    #    Option A: consolidated llm_usage_partB.json anywhere
    #    Option B: per-task llm_task_X_Y.json inside partb_folder
    for path in all_paths:
        fname = path.split("/")[-1].lower()
        if re.match(r'llm.*usage.*part.?b.*\.json', fname, re.IGNORECASE):
            file_map["llm_jsons_partb"] = [path]
            file_map["has_consolidated_llm_b"] = True
            break

    if not file_map["has_consolidated_llm_b"] and partb:
        per_task = []
        for path in all_paths:
            if not path.startswith(partb + "/"):
                continue
            fname = path.split("/")[-1].lower()
            if re.match(r'llm.*task.*\d.*\d.*\.json', fname):
                per_task.append(path)
        file_map["llm_jsons_partb"] = per_task

    # 7. Find requirements.txt anywhere
    for path in all_paths:
        if path.split("/")[-1].lower() == "requirements.txt":
            file_map["requirements"] = path
            break

    # 8. Find data/ folder inside partb
    if partb:
        data_pattern = f"{partb}/data"
        for d in dirs:
            if d.lower() == data_pattern.lower():
                file_map["data_folder"] = d
                # Check for README inside data folder
                for path in all_paths:
                    if path.startswith(d + "/") and path.split("/")[-1].lower().startswith("readme"):
                        file_map["data_readme"] = path
                        break
                break

    # 9. Find results/ folder inside partb
    if partb:
        for d in dirs:
            rel = d[len(partb) + 1:] if d.startswith(partb + "/") else ""
            if rel.lower() in ("results", "result") and "/" not in rel:
                file_map["results_folder"] = d
                file_map["results_files"] = [
                    p.split("/")[-1] for p in all_paths
                    if p.startswith(d + "/") and "/" not in p[len(d) + 1:]
                ]
                break

    return file_map


def get_file_map(owner: str, repo: str, branch: str = "main") -> dict | None:
    """
    Get the complete file map for a repo. Returns None if tree API fails.
    This is the single entry point — call once per student, reuse everywhere.
    """
    tree = fetch_repo_tree(owner, repo, branch)
    if tree is None:
        return None

    file_map = build_file_map(tree)

    # Log summary
    partb = file_map["partb_folder"] or "NOT FOUND"
    nb_count = len(file_map["notebooks"])
    report = file_map["report"].split("/")[-1] if file_map["report"] else "NONE"
    llm_a = "yes" if file_map["llm_json_parta"] else "no"
    llm_b_count = len(file_map["llm_jsons_partb"])
    llm_b_type = "consolidated" if file_map["has_consolidated_llm_b"] else f"{llm_b_count} per-task"
    req = "yes" if file_map["requirements"] else "no"
    print(f"    File map: partB={partb}, notebooks={nb_count}/8, report={report}, llm_a={llm_a}, llm_b={llm_b_type}, req={req}")

    return file_map


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

    # Use file_map for discovery (single API call) with fallback
    fm = get_file_map(owner, repo, branch)
    result["file_map"] = fm

    json_content = None
    json_found_path = None

    if fm and fm["llm_json_parta"]:
        # Tree API found the file
        json_found_path = fm["llm_json_parta"]
        json_content = fetch_file_content(owner, repo, json_found_path, branch)
    else:
        # Fallback: search multiple locations sequentially
        llm_json_candidates = [
            "llm_usage_partA.json",
            "LLM_usage_partA.json",
            "llm_usage.json",
            "partA/llm_usage_partA.json",
            "partA/llm_usage_log.json",
            "partA/LLM_usage_partA.json",
        ]
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
        branch = "main"
    else:
        branch = repo_info.get("default_branch", "main")

    # Use file_map for all discovery (single API call)
    fm = get_file_map(owner, repo, branch)
    result["file_map"] = fm

    required_notebooks_canonical = [
        "task_1_1", "task_1_2", "task_1_3",
        "task_2_1", "task_2_2", "task_2_3",
        "task_3_1", "task_3_2",
    ]
    required_llm_jsons = [
        "llm_task_1_1.json", "llm_task_1_2.json", "llm_task_1_3.json",
        "llm_task_2_1.json", "llm_task_2_2.json", "llm_task_2_3.json",
        "llm_task_3_1.json", "llm_task_3_2.json",
        "llm_task_4_1.json", "llm_task_4_2.json",
    ]

    if fm:
        # --- File map available: use it for all checks ---
        partb_folder = fm["partb_folder"]
        result["partb_folder"] = partb_folder or "partB"
        result["checks"]["partb_folder_exists"] = partb_folder is not None

        if not partb_folder:
            result["flags"].append("PARTB_FOLDER_MISSING")
            result["penalty"] = -20
            return result

        # Notebooks
        found_notebooks = [t for t in required_notebooks_canonical if t in fm["notebooks"]]
        missing_notebooks = [t for t in required_notebooks_canonical if t not in fm["notebooks"]]
        result["checks"]["notebooks_found"] = [f"{t}.ipynb" for t in found_notebooks]
        result["checks"]["notebooks_missing"] = [f"{t}.ipynb" for t in missing_notebooks]

        # Report
        result["checks"]["report_exists"] = fm["report"] is not None
        result["checks"]["report_filename"] = fm["report"].split("/")[-1] if fm["report"] else None

        # Requirements
        result["checks"]["requirements_exists"] = fm["requirements"] is not None

        # Data folder
        result["checks"]["data_folder_exists"] = fm["data_folder"] is not None
        result["checks"]["data_has_readme"] = fm["data_readme"] is not None

        # Results folder
        result["checks"]["results_folder_exists"] = fm["results_folder"] is not None
        result["checks"]["results_files"] = fm["results_files"]

        # LLM JSONs
        has_consolidated = fm["has_consolidated_llm_b"]
        if has_consolidated:
            found_jsons = required_llm_jsons
            missing_jsons = []
        else:
            # Match per-task files from file_map
            found_jsons = []
            missing_jsons = []
            llm_b_names = {p.split("/")[-1].lower() for p in fm["llm_jsons_partb"]}
            for jf in required_llm_jsons:
                if jf.lower() in llm_b_names:
                    found_jsons.append(jf)
                else:
                    missing_jsons.append(jf)

        result["checks"]["llm_jsons_found"] = found_jsons
        result["checks"]["llm_jsons_missing"] = missing_jsons
        result["checks"]["llm_jsons_score"] = len(found_jsons) * 1.5
        result["checks"]["has_consolidated_llm"] = has_consolidated

        # Flags
        if missing_notebooks:
            result["flags"].append(f"MISSING_NOTEBOOKS: {[f'{t}.ipynb' for t in missing_notebooks]}")
        if not fm["report"]:
            result["flags"].append("REPORT_MISSING")
        if not fm["requirements"]:
            result["flags"].append("REQUIREMENTS_MISSING")
        if missing_jsons and not has_consolidated:
            result["flags"].append(f"MISSING_LLM_JSONS: {missing_jsons}")

        # Notebook output check
        for task_name in found_notebooks:
            nb_path = fm["notebooks"][task_name]
            nb_name = nb_path.split("/")[-1]
            nb_content = fetch_file_content(owner, repo, nb_path, branch)
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

    else:
        # --- Fallback: old sequential approach ---
        partb_folder = "partB"
        partb_contents = []
        for candidate in ["partB", "part-B", "Part_B", "Part-B", "part_B", "PartB", "part_b", "PARTB"]:
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

        def find_notebook(expected_name, files_dict):
            if expected_name in files_dict:
                return expected_name
            alt = expected_name.replace("task_", "task")
            if alt in files_dict:
                return alt
            for fname in files_dict:
                if fname.lower() == expected_name.lower() or fname.lower() == alt.lower():
                    return fname
            num_part = expected_name.replace("task_", "").replace(".ipynb", "").replace("_", "")
            for fname in files_dict:
                if fname.endswith(".ipynb") and num_part in fname.replace("_", ""):
                    return fname
            return None

        found_notebooks = []
        missing_notebooks = []
        for nb in [f"{t}.ipynb" for t in required_notebooks_canonical]:
            match = find_notebook(nb, partb_files)
            if match:
                found_notebooks.append(nb)
            else:
                missing_notebooks.append(nb)

        result["checks"]["notebooks_found"] = found_notebooks
        result["checks"]["notebooks_missing"] = missing_notebooks

        report_found = any("report" in f.lower() and (f.lower().endswith(".pdf") or f.lower().endswith(".md") or f.lower().endswith(".docx")) for f in partb_files)
        result["checks"]["report_exists"] = report_found
        result["checks"]["report_filename"] = next((f for f in partb_files if "report" in f.lower()), None)
        result["checks"]["requirements_exists"] = "requirements.txt" in partb_files

        if missing_notebooks:
            result["flags"].append(f"MISSING_NOTEBOOKS: {missing_notebooks}")
        if not report_found:
            result["flags"].append("REPORT_MISSING")
        if not result["checks"]["requirements_exists"]:
            result["flags"].append("REQUIREMENTS_MISSING")

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
