"""Pluggable multi-provider LLM layer with automatic fallback.

`generate_structured(prompt, schema, system)` returns a validated Pydantic
object. It walks `config.PROVIDER_ORDER` and uses the first provider that has an
API key and responds successfully; on error/rate-limit it falls through.

Adding a model later:
  * OpenAI-compatible provider  -> no code. Add its key + name in
    LLM_PROVIDER_ORDER (and <NAME>_BASE_URL/_MODEL if not in config._KNOWN).
  * New API shape (e.g. another vendor) -> add one adapter function and register
    it in _ADAPTERS keyed by `kind`. Everything else stays the same.

Every milestone (M1 profile, M3 matching, M5 messages) reuses this, so provider
behaviour lives in exactly one place.
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)

# transient = worth retrying the SAME provider before falling through
_TRANSIENT = ("503", "429", "500", "502", "504", "unavailable", "overloaded",
              "high demand", "timeout", "timed out", "rate limit", "try again")


def _is_transient(err: Exception) -> bool:
    return any(t in str(err).lower() for t in _TRANSIENT)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Pull a JSON object out of a reply that may be wrapped in prose/fences."""
    text = (text or "").strip()
    m = _JSON_FENCE.search(text)
    if m:
        return m.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


# ---------------------------------------------------------------- adapters
# Each adapter: (cfg, prompt, schema, system) -> validated schema instance.


def _openai_compatible(cfg: dict, prompt: str, schema: type[T], system: str | None) -> T:
    from openai import OpenAI

    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
    sys_msg = (
        (system + "\n\n" if system else "")
        + "Respond with ONLY a single JSON object — no markdown, no commentary. "
        + "It MUST conform to this JSON schema:\n"
        + json.dumps(schema.model_json_schema())
    )
    kwargs = dict(
        model=cfg["model"],
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=8000,
    )
    try:
        resp = client.chat.completions.create(
            response_format={"type": "json_object"}, **kwargs
        )
    except Exception:
        resp = client.chat.completions.create(**kwargs)  # provider lacks json mode
    return schema.model_validate_json(_extract_json(resp.choices[0].message.content))


def _gemini(cfg: dict, prompt: str, schema: type[T], system: str | None) -> T:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=cfg["api_key"])
    resp = client.models.generate_content(
        model=cfg["model"],
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2,
        ),
    )
    if resp.parsed is not None:
        return resp.parsed  # type: ignore[return-value]
    return schema.model_validate_json(_extract_json(resp.text))


def _anthropic(cfg: dict, prompt: str, schema: type[T], system: str | None) -> T:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg["api_key"])
    resp = client.messages.parse(
        model=cfg["model"],
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=schema,
    )
    if resp.parsed_output is None:
        raise RuntimeError(f"empty output (stop_reason={resp.stop_reason})")
    return resp.parsed_output


_ADAPTERS: dict[str, Callable[..., BaseModel]] = {
    "openai": _openai_compatible,
    "gemini": _gemini,
    "anthropic": _anthropic,
}


# ---------------------------------------------------------------- public API


def generate_structured(
    prompt: str, schema: type[T], system: str | None = None, *, verbose: bool = True
) -> T:
    """Return a validated `schema` instance, trying providers in order."""
    errors: list[str] = []
    for name in config.PROVIDER_ORDER:
        cfg = config.provider_config(name)
        adapter = _ADAPTERS.get(cfg["kind"])
        if adapter is None:
            errors.append(f"{name}: unknown kind '{cfg['kind']}'")
            continue
        if not cfg["api_key"]:
            errors.append(f"{name}: no {cfg['key_env']} set")
            continue
        if not cfg["model"]:
            errors.append(f"{name}: no model (set {name.upper()}_MODEL)")
            continue
        # retry the same provider a couple of times on transient errors,
        # then fall through to the next provider on any failure.
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                if verbose:
                    suffix = f" (retry {attempt})" if attempt > 1 else ""
                    print(f"      -> trying {name} ({cfg['model']}){suffix} ...")
                result = adapter(cfg, prompt, schema, system)
                if verbose:
                    print(f"      <- {name} OK")
                return result  # type: ignore[return-value]
            except Exception as e:  # noqa: BLE001
                msg = (str(e).splitlines() or [""])[0][:160] or type(e).__name__
                if _is_transient(e) and attempt < attempts:
                    if verbose:
                        print(f"      .. {name} transient ({msg}); retrying in 3s")
                    time.sleep(3)
                    continue
                if verbose:
                    print(f"      !! {name} failed: {msg}")
                errors.append(f"{name}: {msg}")
                break  # non-transient or out of retries -> next provider
    raise RuntimeError("All LLM providers failed:\n  " + "\n  ".join(errors))
