#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TeamSpec V1.1 FREEZE - minimal backend integration example.

Requirements:
    pip install openai jsonschema

Environment:
    OPENAI_API_KEY=...
"""

import json
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI

HERE = Path(__file__).resolve().parent
PROMPT_PATH = HERE / "intent_parser_prompt_team_v1_1_FINAL.txt"
SCHEMA_PATH = HERE / "user_intent_schema_team_v1_1.json"
MODEL = "gpt-5.6-terra"


def parse_user_intent(user_input: str, current_datetime: str, timezone: str = "Asia/Seoul") -> dict:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_text = json.dumps(schema, ensure_ascii=False)

    runtime_context = {
        "current_datetime": current_datetime,
        "timezone": timezone,
    }

    client = OpenAI()
    response = client.responses.create(
        model=MODEL,
        instructions=prompt + "\n\n# JSON Schema\n" + schema_text,
        input=[
            {
                "role": "developer",
                "content": (
                    "Runtime context for this request:\n"
                    + json.dumps(runtime_context, ensure_ascii=False)
                    + "\nUse it only when required to interpret relative time."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Return exactly one valid JSON object only. "
                    "Follow the provided JSON Schema exactly. "
                    "Do not use Markdown or explanations.\n\n"
                    f"User request:\n{user_input}"
                ),
            },
        ],
        text={"format": {"type": "json_object"}},
        reasoning={"effort": "none"},
        prompt_cache_key="intent-parser-team-v1-1",
        max_output_tokens=500,
    )

    intent = json.loads(response.output_text)
    Draft202012Validator(schema).validate(intent)

    min_m = intent.get("desired_duration_min_minutes")
    max_m = intent.get("desired_duration_max_minutes")
    if min_m is not None and max_m is not None and min_m > max_m:
        raise ValueError("Semantic validation failed: desired duration min > max")

    return intent


if __name__ == "__main__":
    result = parse_user_intent(
        "지금 사당인데 7시에 잠실 약속 있어. 그사이에 카페 가고 싶어.",
        current_datetime="2026-08-28T17:00:00+09:00",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
