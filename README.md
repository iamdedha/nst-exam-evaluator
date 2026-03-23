# NST Exam Evaluator

Automated evaluation pipeline for Newton School of Technology's Advanced Machine Learning Mid-Semester Exam. Uses LLM-powered grading (OpenRouter/Claude Sonnet or Google Gemini) with multi-agent evaluation across three exam parts.

## Exam Structure

| Part | Weight | What It Evaluates |
|------|--------|-------------------|
| **Part A** | 5% (50 raw marks) | Paper selection, LLM usage disclosure, reproducibility assessment, analytical prompts |
| **Part B** | 30% (130 raw marks) | Paper understanding, code reproduction, ablation study, report writing |
| **Part C** | 5% (5 marks) | Cross-verification of Part B work (recall questions to verify authenticity) |

## Prerequisites

- **Python 3.10+**
- **API Key** (one of the following):
  - [OpenRouter API Key](https://openrouter.ai/keys) (recommended, uses Claude Sonnet) - paid
  - [Google Gemini API Key](https://aistudio.google.com/apikey) - free
- **GitHub Personal Access Token** (for fetching student repos):
  - Go to https://github.com/settings/tokens
  - Generate new token (classic), no scopes needed for public repos
  - Without this token, you're limited to 60 GitHub API requests/hour (vs 5000 with token)

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/iamdedha/nst-exam-evaluator.git
cd nst-exam-evaluator
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Environment Variables

**On macOS/Linux:**
```bash
export LLM_PROVIDER=openrouter          # or "gemini"
export OPENROUTER_API_KEY=sk-or-v1-...  # if using OpenRouter
export GEMINI_API_KEY=AIza...           # if using Gemini
export GITHUB_TOKEN=ghp_...             # GitHub personal access token
export SKIP_PAPER_FETCH=true            # optional: skip downloading full paper PDFs
```

**On Windows (PowerShell):**
```powershell
$env:LLM_PROVIDER = "openrouter"
$env:OPENROUTER_API_KEY = "sk-or-v1-..."
$env:GEMINI_API_KEY = "AIza..."
$env:GITHUB_TOKEN = "ghp_..."
$env:SKIP_PAPER_FETCH = "true"
```

### 4. Place Input Files

Place these files in the project root (parent of `evaluator/`):

| File | Description |
|------|-------------|
| `Advance ML Midsem Part A Submission Form (Responses).xlsx` | Part A student submissions |
| `Advance ML Midsem Part B Submission Form (Responses) - Form Responses 1.csv` | Part B submissions (CSV) |
| `Advance ML Midsem Submissions - RU.xlsx` | Part C recall answers (from RU platform) |

Or place them in a `Latest_part_a_b_c/` folder in the project root.

### 5. Run the Full Pipeline

```bash
cd evaluator
python run_evaluation.py --all
```

This runs all phases sequentially: Phase 0 -> Part A -> Part B -> Part C -> Aggregation.

## CLI Usage

```bash
# Run everything
python run_evaluation.py --all

# Run individual phases
python run_evaluation.py --phase0           # Data cleanup & deduplication only
python run_evaluation.py --part-a           # Part A evaluation only
python run_evaluation.py --part-b           # Part B evaluation only
python run_evaluation.py --part-c           # Part C cross-verification only
python run_evaluation.py --aggregate        # Score aggregation only

# Evaluate a single student
python run_evaluation.py --part-a-student 230049
python run_evaluation.py --part-b-student 230091

# Combine phases
python run_evaluation.py --phase0 --part-a --aggregate
```

## Pipeline Phases

### Phase 0: Data Cleanup
- Parses Excel/CSV submission files
- Detects resubmissions (20% penalty per extra submission)
- Detects duplicate papers (first-come-first-serve, later submissions disqualified)
- Validates required fields (paper title, venue, year, GitHub link)
- Outputs: `output/phase0_summary.json`

### Part A Evaluation (50 marks -> scaled to 5%)
Uses a two-tier evaluation system:

**Tier 1 - Deterministic (automated checks):**
- Paper validity: year (4), venue (5), method alignment (4), paper type (2)
- LLM disclosure: JSON file validity (4), completeness (3), verification (3)

**Tier 2 - LLM-based (AI grading):**
- Reproducibility: dataset availability (5), compute feasibility (5), experimental scope (5)
- Top 5 prompts: analytical depth (6), relevance (4)

Each student's GitHub repo is checked for:
- `llm_usage_partA.json` (multiple path candidates searched)
- Repository structure and content

**Outputs:** `output/part_a_scores/` (individual) + `output/part_a_all_results.json` (aggregate)

### Part B Evaluation (130 marks -> scaled to 30%)
Evaluates 4 questions with sub-tasks:

| Question | Sub-tasks | Marks |
|----------|-----------|-------|
| Q1: Paper Understanding | Task 1.1 (8), Task 1.2 (8), Task 1.3 (9) | 25 |
| Q2: Code Reproduction | Task 2.1 (5), Task 2.2 (20), Task 2.3 (15) | 40 |
| Q3: Ablation Study | Task 3.1 (20), Task 3.2 (15) | 35 |
| Q4: Report & LLM Usage | Task 4.1 (15), Task 4.2 (15) | 30 |

For each student:
1. Fetches all task notebooks from GitHub (`partB/task_X_Y.ipynb`)
2. Fetches report PDF (`partB/report.pdf`)
3. Generates ground truth from the paper using LLM
4. Evaluates each notebook against ground truth using LLM
5. Checks for LLM usage JSON files per task
6. Applies structure penalty if `partB/` folder is missing

**Outputs:** `output/part_b_scores/` (individual) + `output/part_b_all_results.json` (aggregate)

### Part C Evaluation (5 marks)
Cross-verification of Part B work:
- 5 recall questions, students answer best 4 out of 5
- Each question worth 1.25 marks
- For each question, fetches the corresponding Part B notebook
- LLM compares the student's recall answer against their actual Part B submission
- Scores coherence: high (1.25), medium (0.75-1.0), low (0.25-0.5), none (0)
- Partial credit allowed

| Part C Question | Maps to Part B Task | Topic |
|----------------|---------------------|-------|
| Q1 (24107) | Task 2.3 | Results & Reproducibility |
| Q2 (24108) | Task 3.1 | Ablation Study |
| Q3 (24109) | Task 3.2 + 1.2 | Failure Mode & Assumptions |
| Q4 (24110) | Task 2.2 | Code Reproduction |
| Q5 (24111) | Task 4.1 | Report/Reflection |

**Outputs:** `output/part_c_scores/` (individual) + `output/part_c_all_results.json` (aggregate)

### Aggregation
Combines all scores into:
- `output/master_scores.csv` - Spreadsheet with all scores
- `output/master_scores.json` - JSON format

## Output Files

```
output/
  phase0_summary.json          # Phase 0 results (valid students, penalties, etc.)
  part_a_all_results.json      # All Part A scores
  part_b_all_results.json      # All Part B scores
  part_c_all_results.json      # All Part C scores
  master_scores.csv            # Final aggregated scores
  master_scores.json           # Final aggregated scores (JSON)
  ground_truths/               # Cached LLM-generated ground truth per paper
  part_a_scores/               # Individual Part A score files
  part_b_scores/               # Individual Part B score files
  part_c_scores/               # Individual Part C score files
```

## API Costs & Rate Limits

### Per Student (approximate LLM calls):
| Phase | LLM Calls | Time |
|-------|-----------|------|
| Part A | 2-3 calls | ~5-8 seconds |
| Part B | 8-12 calls | ~60-90 seconds |
| Part C | 4-5 calls | ~30-50 seconds |

### For 100 Students:
| Provider | Est. Calls | Est. Cost | Est. Time |
|----------|-----------|-----------|-----------|
| OpenRouter (Claude Sonnet) | ~1,500 | ~$3-5 | ~45-60 min |
| Gemini Free | ~1,500 | $0 | ~3-4 hours (rate limited) |

### Rate Limits:
- **OpenRouter**: ~50 requests/min (automatic retry on 429)
- **Gemini Free**: 15 requests/min (much slower)
- **GitHub API**: 60/hour without token, 5000/hour with `GITHUB_TOKEN`

## Web Dashboard

A Flask web app is included for visual evaluation:

```bash
cd evaluator
python -m webapp.app
```

Then open `http://localhost:5000` in your browser.

Features:
- Upload Part A, B, C files via browser
- Real-time evaluation progress with live logs
- Interactive Plotly charts (score distribution, method breakdown)
- Student detail view with per-component scores
- Export results as CSV/JSON

### Deploy on Render (limitations)
The app is deployed at `nst-exam-evaluator.onrender.com` but Render's free tier has a 30-second proxy timeout, so Part B and Part C evaluation may time out. Part A works fine on Render.

For full evaluation, run locally.

## Project Structure

```
evaluator/
  run_evaluation.py              # CLI entry point
  phase0_data_cleanup.py         # Phase 0: data parsing & dedup
  agents/
    llm_client.py                # LLM API wrapper (OpenRouter + Gemini with fallback)
    github_checker.py            # GitHub repo validation & file fetching
    paper_fetcher.py             # Paper PDF download
    paper_ground_truth.py        # LLM-generated ground truth per paper
    part_a_evaluator.py          # Part A: two-tier evaluation
    part_b_evaluator.py          # Part B: notebook + report grading
    part_c_evaluator.py          # Part C: cross-verification
    sub_agents.py                # Sub-agents for complex tasks (annotation, citation, depth)
  config/
    llm_config.py                # LLM provider configuration
  webapp/
    app.py                       # Flask entry point
    config.py                    # Flask config
    routes/                      # 5 blueprints (main, upload, evaluation, results, export)
    services/                    # Pipeline, progress tracking, run management
    templates/                   # HTML templates with Tailwind CSS
  output/                        # Evaluation results (gitignored)
```

## Troubleshooting

### "LLM_JSON_MISSING" flag
The student's `llm_usage_partA.json` file wasn't found in their GitHub repo. The evaluator searches multiple paths:
- Root: `llm_usage_partA.json`, `LLM_usage_partA.json`, `llm_usage.json`
- Subdirectory: `partA/llm_usage_partA.json`, `partA/LLM_usage_partA.json`

### GitHub rate limiting (403 errors)
Set the `GITHUB_TOKEN` environment variable. Without it, you're limited to 60 requests/hour.

### LLM calls failing
- Check your API key is valid
- The system automatically falls back between OpenRouter and Gemini if one fails
- Check rate limits: Gemini free tier is 15 req/min

### Phase 0 finds fewer students than expected
- Resubmissions are deduplicated (latest kept, 20% penalty applied)
- Duplicate papers are caught (first-come-first-serve)
- Missing required fields cause disqualification

## License

Internal tool for Newton School of Technology. Not for public distribution.
