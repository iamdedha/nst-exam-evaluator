"""
LLM Configuration - Supports OpenRouter (primary) and Google Gemini (fallback) APIs
"""
import os

# --- Provider Selection ---
# Set to "openrouter" (default, paid) or "gemini" (fallback, free tier)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")

# --- OpenRouter Config ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "anthropic/claude-sonnet-4"

# --- Google Gemini Config (fallback) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"  # Free tier: 15 RPM, 1000 RPD

# --- Common Settings ---
MODEL = OPENROUTER_MODEL if LLM_PROVIDER == "openrouter" else GEMINI_MODEL
MODEL_LIGHT = MODEL
MAX_TOKENS = 8192
TEMPERATURE = 0.0  # Deterministic for grading consistency

# --- Warnings ---
if LLM_PROVIDER == "openrouter" and not OPENROUTER_API_KEY:
    print("WARNING: LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is empty. Set it via env var or it will fall back to Gemini.")
if LLM_PROVIDER == "gemini" and not GEMINI_API_KEY:
    print("WARNING: LLM_PROVIDER=gemini but GEMINI_API_KEY is empty.")
