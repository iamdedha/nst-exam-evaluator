"""
LLM Configuration - Supports OpenAI, OpenRouter, and Google Gemini APIs
"""
import os

# --- Provider Selection ---
# Set to "openai", "openrouter", or "gemini"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")

# --- OpenAI Config ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

# --- OpenRouter Config ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "anthropic/claude-sonnet-4"

# --- Google Gemini Config (fallback) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

# --- Common Settings ---
if LLM_PROVIDER == "openai":
    MODEL = OPENAI_MODEL
elif LLM_PROVIDER == "openrouter":
    MODEL = OPENROUTER_MODEL
else:
    MODEL = GEMINI_MODEL
MODEL_LIGHT = MODEL
MAX_TOKENS = 8192
TEMPERATURE = 0.0  # Deterministic for grading consistency

# --- Warnings ---
if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
    print("WARNING: LLM_PROVIDER=openai but OPENAI_API_KEY is empty.")
if LLM_PROVIDER == "openrouter" and not OPENROUTER_API_KEY:
    print("WARNING: LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is empty.")
if LLM_PROVIDER == "gemini" and not GEMINI_API_KEY:
    print("WARNING: LLM_PROVIDER=gemini but GEMINI_API_KEY is empty.")
