"""
LLM Client - Supports OpenAI, OpenRouter, and Google Gemini APIs.
"""

import json
import time
import requests
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.llm_config import (
    LLM_PROVIDER, OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    GEMINI_API_KEY, GEMINI_MODEL, MODEL, MAX_TOKENS, TEMPERATURE,
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
)


def _call_openai(prompt: str, system_prompt: str, model: str, max_tokens: int, temperature: float, retries: int) -> str:
    """Call OpenAI API."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model or OPENAI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    for attempt in range(retries):
        try:
            response = requests.post(
                OPENAI_BASE_URL,
                headers=headers,
                json=payload,
                timeout=90,
            )

            if response.status_code == 429:
                wait = 2 ** (attempt + 1)
                print(f"  OpenAI rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()

            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                print(f"  Unexpected OpenAI response: {data}")
                return ""

        except requests.exceptions.Timeout:
            print(f"  OpenAI timeout on attempt {attempt + 1}/{retries}")
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            print(f"  OpenAI error on attempt {attempt + 1}/{retries}: {e}")
            time.sleep(2)

    return ""


def _call_openrouter(prompt: str, system_prompt: str, model: str, max_tokens: int, temperature: float, retries: int) -> str:
    """Call OpenRouter API."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "exam-evaluator",
        "X-Title": "NST Exam Evaluator",
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    for attempt in range(retries):
        try:
            response = requests.post(
                OPENROUTER_BASE_URL,
                headers=headers,
                json=payload,
                timeout=60,
            )

            if response.status_code == 429:
                wait = 2 ** (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()

            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                print(f"  Unexpected response: {data}")
                return ""

        except requests.exceptions.Timeout:
            print(f"  Timeout on attempt {attempt + 1}/{retries}")
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            print(f"  Request error on attempt {attempt + 1}/{retries}: {e}")
            time.sleep(2)

    return ""


def _call_gemini(prompt: str, system_prompt: str, model: str, max_tokens: int, temperature: float, retries: int) -> str:
    """Call Google Gemini API."""
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)

    generation_config = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "response_mime_type": "text/plain",
    }

    gemini_model = genai.GenerativeModel(
        model_name=model or GEMINI_MODEL,
        generation_config=generation_config,
        system_instruction=system_prompt if system_prompt else None,
    )

    for attempt in range(retries):
        try:
            response = gemini_model.generate_content(prompt)

            if response and response.text:
                return response.text
            else:
                # Check for blocked content
                if response.prompt_feedback:
                    print(f"  Gemini blocked: {response.prompt_feedback}")
                return ""

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RATE_LIMIT" in error_str.upper():
                wait = min(2 ** (attempt + 1) * 3, 30)  # Cap at 30s wait
                print(f"  Gemini rate limited, waiting {wait}s (attempt {attempt+1}/{retries})...")
                time.sleep(wait)
                continue
            elif "500" in error_str or "503" in error_str:
                print(f"  Gemini server error on attempt {attempt + 1}/{retries}: {e}")
                time.sleep(3)
                continue
            else:
                print(f"  Gemini error on attempt {attempt + 1}/{retries}: {e}")
                time.sleep(2)
                if attempt == retries - 1:
                    return ""

    return ""


def call_llm(prompt: str, system_prompt: str = "", model: str = None, max_tokens: int = None, temperature: float = None, retries: int = 2) -> str:
    """
    Call LLM API and return the response text.
    Routes to the configured provider with automatic fallback to the other.
    """
    model = model or MODEL
    max_tokens = max_tokens or MAX_TOKENS
    temperature = temperature if temperature is not None else TEMPERATURE

    if LLM_PROVIDER == "openai" and OPENAI_API_KEY:
        result = _call_openai(prompt, system_prompt, model, max_tokens, temperature, retries)
        if result:
            return result
        # Fallback chain
        if OPENROUTER_API_KEY:
            print("  OpenAI failed, falling back to OpenRouter...")
            return _call_openrouter(prompt, system_prompt, OPENROUTER_MODEL, max_tokens, temperature, retries)
        if GEMINI_API_KEY:
            print("  OpenAI failed, falling back to Gemini...")
            return _call_gemini(prompt, system_prompt, GEMINI_MODEL, max_tokens, temperature, retries)
        return ""
    elif LLM_PROVIDER == "openrouter" and OPENROUTER_API_KEY:
        result = _call_openrouter(prompt, system_prompt, model, max_tokens, temperature, retries)
        if result:
            return result
        if GEMINI_API_KEY:
            print("  OpenRouter failed, falling back to Gemini...")
            return _call_gemini(prompt, system_prompt, GEMINI_MODEL, max_tokens, temperature, retries)
        return ""
    elif LLM_PROVIDER == "gemini" and GEMINI_API_KEY:
        result = _call_gemini(prompt, system_prompt, model, max_tokens, temperature, retries)
        if result:
            return result
        # Fallback to OpenRouter
        if OPENROUTER_API_KEY:
            print("  Gemini failed, falling back to OpenRouter...")
            return _call_openrouter(prompt, system_prompt, OPENROUTER_MODEL, max_tokens, temperature, retries)
        return ""
    else:
        # Try whichever has a key
        if OPENROUTER_API_KEY:
            return _call_openrouter(prompt, system_prompt, OPENROUTER_MODEL, max_tokens, temperature, retries)
        elif GEMINI_API_KEY:
            return _call_gemini(prompt, system_prompt, GEMINI_MODEL, max_tokens, temperature, retries)
        print("  ERROR: No LLM API key configured. Set OPENROUTER_API_KEY or GEMINI_API_KEY.")
        return ""


def call_llm_json(prompt: str, system_prompt: str = "", model: str = None) -> dict:
    """
    Call LLM and parse the response as JSON.
    Extracts JSON from markdown code blocks if needed.
    """
    response = call_llm(prompt, system_prompt, model)

    if not response:
        return {}

    # Try direct parse
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Try extracting from code block
    if "```json" in response:
        try:
            start = response.index("```json") + 7
            end = response.index("```", start)
            return json.loads(response[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass

    if "```" in response:
        try:
            start = response.index("```") + 3
            newline = response.index("\n", start)
            start = newline + 1
            end = response.index("```", start)
            return json.loads(response[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Try finding JSON object in response
    for i, c in enumerate(response):
        if c == '{':
            # Find matching closing brace
            depth = 0
            for j in range(i, len(response)):
                if response[j] == '{':
                    depth += 1
                elif response[j] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(response[i:j+1])
                        except json.JSONDecodeError:
                            break
            break

    print(f"  Failed to parse JSON from LLM response (length={len(response)})")
    return {"_raw_response": response}
