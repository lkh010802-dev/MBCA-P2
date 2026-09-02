#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Production-oriented Luna Hybrid intent parser.

Returns Structured Output from GPT-5.6 Luna, then applies conservative
local normalization from intent_postprocess.py.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

from intent_postprocess import postprocess_intent

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

PROMPT_PATH = HERE / "intent_parser_prompt_team_v1_3_COST_OPT.txt"
SCHEMA_PATH = HERE / "user_intent_schema_team_v1_3_STRICT.json"
DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_CACHE_KEY = "intent-parser-team-v1-3-16field-candidate"


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


def parse_intent(
    user_input: str,
    runtime_context: Optional[Dict[str, Any]] = None,
    *,
    model: str = DEFAULT_MODEL,
    include_debug: bool = False,
) -> Dict[str, Any]:
    """Parse one user utterance into the backend intent schema."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(".env에 OPENAI_API_KEY가 필요합니다.")

    context = runtime_context or {}
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    client = OpenAI()

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "developer",
                "content": [{
                    "type": "input_text",
                    "text": prompt,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }],
            },
            {
                "role": "developer",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "Runtime Context (output field가 아님; 상대시간 계산에만 사용):\n"
                        + json.dumps(context, ensure_ascii=False)
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
                "schema": schema,
            }
        },
        reasoning={"effort": "none"},
        prompt_cache_key=DEFAULT_CACHE_KEY,
        prompt_cache_options={"mode": "explicit", "ttl": "30m"},
        max_output_tokens=300,
    )

    llm_intent = json.loads(response.output_text.strip())
    final_intent, changes = postprocess_intent(user_input, context, llm_intent)

    if not include_debug:
        return final_intent

    return {
        "intent": final_intent,
        "llm_intent": llm_intent,
        "postprocess_changes": changes,
        "usage": _usage(response),
    }
