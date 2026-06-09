"""Central config: loads .env, exposes paths, and builds the LLM provider registry.

Adding a new model in the future is meant to be easy:

  * Any OpenAI-compatible provider (NVIDIA, Groq, OpenRouter, DeepSeek, Together,
    OpenAI, ...) needs ZERO code. Add its key + put its name in
    LLM_PROVIDER_ORDER. If it's not in `_KNOWN` below, also set
    <NAME>_BASE_URL and <NAME>_MODEL.

  * A provider with a genuinely different API (e.g. Gemini) needs one small
    adapter in src/llm.py keyed by `kind`.

Example .env to add Groq as a third fallback:
    LLM_PROVIDER_ORDER=nvidia,gemini,groq
    GROQ_API_KEY=gsk_...
    # GROQ_BASE_URL / GROQ_MODEL already defaulted in _KNOWN

Per-provider overrides via env: <NAME>_API_KEY, <NAME>_MODEL, <NAME>_BASE_URL.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESUMES_DIR = DATA_DIR / "resumes"
DB_DIR = DATA_DIR / "db"
PROFILE_PATH = DATA_DIR / "profile.json"

load_dotenv(ROOT / ".env")


# ---- LLM provider registry --------------------------------------------------
# name -> (kind, default_base_url, default_model)
#   kind "openai" = OpenAI-compatible chat/completions API
#   kind "gemini" = Google AI Studio
# Anything not listed defaults to kind "openai" (set <NAME>_BASE_URL + _MODEL).
_KNOWN: dict[str, tuple[str, str | None, str | None]] = {
    "nvidia": ("openai", "https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct"),
    "gemini": ("gemini", None, "gemini-2.5-flash"),
    "groq": ("openai", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openrouter": ("openai", "https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct"),
    "openai": ("openai", "https://api.openai.com/v1", "gpt-4o-mini"),
    "deepseek": ("openai", "https://api.deepseek.com", "deepseek-chat"),
    "together": ("openai", "https://api.together.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "anthropic": ("anthropic", None, "claude-opus-4-8"),
}

PROVIDER_ORDER = [
    p.strip()
    for p in os.getenv("LLM_PROVIDER_ORDER", "nvidia,gemini").split(",")
    if p.strip()
]


def provider_config(name: str) -> dict:
    """Resolve a provider's config from `_KNOWN` defaults + env overrides."""
    kind, base, model = _KNOWN.get(name, ("openai", None, None))
    up = name.upper()
    return {
        "name": name,
        "kind": os.getenv(f"{up}_KIND", kind),
        "base_url": os.getenv(f"{up}_BASE_URL", base),
        "model": os.getenv(f"{up}_MODEL", model),
        "key_env": f"{up}_API_KEY",
        "api_key": os.getenv(f"{up}_API_KEY"),
    }


def require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing {name}. Add it to {ROOT / '.env'} "
            f"(copy .env.example to .env and fill it in)."
        )
    return value


def get(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)
