#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Production-oriented Luna Hybrid intent parser with resilience.

Core intent policy:
    GPT-5.6 Luna -> strict 16-field Structured Output -> V1.3.1 postprocess

Runtime safety layer:
    bounded deadline -> at most one controlled retry -> circuit breaker
    -> exact-result cache for time-independent inputs -> deterministic fallback

The backend-facing return value remains the same 16-field JSON object unless
include_debug=True is requested.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import openai
from dotenv import load_dotenv
from jsonschema import Draft202012Validator
from openai import OpenAI

from intent_postprocess import postprocess_intent
from runtime_resilience import (
    CircuitBreaker,
    LocalOutputError,
    ResilienceConfig,
    ResultCache,
    execute_with_resilience,
)

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

PROMPT_PATH = HERE / "intent_parser_prompt_team_v1_3_COST_OPT.txt"
SCHEMA_PATH = HERE / "user_intent_schema_team_v1_3_STRICT.json"
DEFAULT_MODEL = "gpt-5.6-luna"
# Prompt/schema did not change from V1.3, so keeping this key preserves prompt-cache locality.
DEFAULT_PROMPT_CACHE_KEY = "intent-parser-team-v1-3-16field-candidate"

_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_SCHEMA_VALIDATOR = Draft202012Validator(_SCHEMA)
_CONFIG = ResilienceConfig.from_env()
_CIRCUIT = CircuitBreaker(
    failure_threshold=_CONFIG.circuit_failure_threshold,
    open_seconds=_CONFIG.circuit_open_seconds,
)
_CLIENT: Optional[OpenAI] = None
_RESULT_CACHE: Optional[ResultCache] = None


def _get_client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        # IMPORTANT: the SDK itself retries selected errors twice by default.
        # Disable that here so our total deadline / one-retry policy is the only retry layer.
        _CLIENT = OpenAI(max_retries=0)
    return _CLIENT


def _get_result_cache() -> Optional[ResultCache]:
    global _RESULT_CACHE
    if not _CONFIG.result_cache_enabled:
        return None
    if _RESULT_CACHE is None:
        cache_path = Path(_CONFIG.result_cache_path)
        if not cache_path.is_absolute():
            cache_path = HERE / cache_path
        try:
            _RESULT_CACHE = ResultCache(str(cache_path), _CONFIG.result_cache_ttl_seconds)
        except Exception:
            # Cache initialization must never make the parser unavailable.
            _RESULT_CACHE = None
    return _RESULT_CACHE


def _get_attr(obj: Any, name: str, default: Any = 0) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(name, default)
    else:
        value = getattr(obj, name, default)
    return default if value is None else value


def _usage(resp: Any) -> Dict[str, int]:
    usage = getattr(resp, "usage", None)
    input_tokens = int(_get_attr(usage, "input_tokens", 0))
    output_tokens = int(_get_attr(usage, "output_tokens", 0))
    details = _get_attr(usage, "input_tokens_details", None)
    out_details = _get_attr(usage, "output_tokens_details", None)
    cached = int(_get_attr(details, "cached_tokens", 0))
    cache_write = int(_get_attr(details, "cache_write_tokens", 0))
    reasoning = int(_get_attr(out_details, "reasoning_tokens", 0))
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": cache_write,
        "uncached_nonwrite_input_tokens": max(input_tokens - cached - cache_write, 0),
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": int(_get_attr(usage, "total_tokens", input_tokens + output_tokens)),
    }


def _semantic_validate(intent: Dict[str, Any]) -> None:
    if intent.get("target_location_text") is None and intent.get("target_location_scope") is not None:
        raise LocalOutputError("target_location_scope requires target_location_text")
    if intent.get("start_time") is not None and intent.get("start_time_period") is not None:
        raise LocalOutputError("start exact time and period cannot coexist")
    if intent.get("end_time") is not None and intent.get("end_time_period") is not None:
        raise LocalOutputError("end exact time and period cannot coexist")
    lo = intent.get("desired_duration_min_minutes")
    hi = intent.get("desired_duration_max_minutes")
    if lo is not None and hi is not None and lo > hi:
        raise LocalOutputError("desired duration min must be <= max")


def _validate_intent(intent: Dict[str, Any]) -> None:
    errors = sorted(_SCHEMA_VALIDATOR.iter_errors(intent), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = ".".join(str(x) for x in first.path) or "<root>"
        raise LocalOutputError(f"schema validation failed at {path}: {first.message}")
    _semantic_validate(intent)


def _is_retryable_error(exc: Exception) -> bool:
    # A malformed/semantically invalid model output is rare but worth one fresh attempt.
    if isinstance(exc, LocalOutputError):
        return True

    retryable_types = tuple(
        t for t in (
            getattr(openai, "APITimeoutError", None),
            getattr(openai, "APIConnectionError", None),
            getattr(openai, "RateLimitError", None),
            getattr(openai, "InternalServerError", None),
        ) if isinstance(t, type)
    )
    if retryable_types and isinstance(exc, retryable_types):
        return True

    status = getattr(exc, "status_code", None)
    return status in {408, 409, 429} or (isinstance(status, int) and status >= 500)


def _call_llm_once(
    user_input: str,
    runtime_context: Dict[str, Any],
    model: str,
    timeout_seconds: float,
) -> Dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = _get_client()
    response = client.with_options(timeout=timeout_seconds, max_retries=0).responses.create(
        model=model,
        input=[
            {
                "role": "developer",
                "content": [{
                    "type": "input_text",
                    "text": _PROMPT,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }],
            },
            {
                "role": "developer",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "Runtime Context (output field가 아님; 상대시간 계산에만 사용):\n"
                        + json.dumps(runtime_context, ensure_ascii=False)
                    ),
                }],
            },
            {"role": "user", "content": [{"type": "input_text", "text": user_input}]},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "team_user_intent_v1_3",
                "strict": True,
                "schema": _SCHEMA,
            }
        },
        reasoning={"effort": "none"},
        prompt_cache_key=DEFAULT_PROMPT_CACHE_KEY,
        prompt_cache_options={"mode": "explicit", "ttl": "30m"},
        max_output_tokens=300,
    )

    try:
        llm_intent = json.loads(response.output_text.strip())
    except Exception as exc:
        raise LocalOutputError("response.output_text is not valid JSON") from exc

    final_intent, changes = postprocess_intent(user_input, runtime_context, llm_intent)
    _validate_intent(final_intent)

    return {
        "intent": final_intent,
        "llm_intent": llm_intent,
        "postprocess_changes": changes,
        "usage": _usage(response),
        "request_id": getattr(response, "_request_id", None),
    }


def parse_intent(
    user_input: str,
    runtime_context: Optional[Dict[str, Any]] = None,
    *,
    model: str = DEFAULT_MODEL,
    include_debug: bool = False,
) -> Dict[str, Any]:
    """Parse one utterance safely.

    Normal path: one Luna call.
    Transient failure: at most one controlled retry inside the total deadline.
    Continued failure: exact result cache (static inputs only), then conservative fallback.
    """
    context = runtime_context or {}

    outcome = execute_with_resilience(
        user_input=user_input,
        runtime_context=context,
        model=model,
        call_llm=lambda timeout: _call_llm_once(user_input, context, model, timeout),
        is_retryable_error=_is_retryable_error,
        validate_intent=_validate_intent,
        config=_CONFIG,
        circuit=_CIRCUIT,
        cache=_get_result_cache(),
    )

    if not include_debug:
        # Backend contract remains exactly the same 16 fields.
        return outcome["intent"]

    return outcome
