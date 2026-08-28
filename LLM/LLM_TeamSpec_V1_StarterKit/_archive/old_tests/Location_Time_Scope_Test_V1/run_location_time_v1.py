#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

load_dotenv(PROJECT_ROOT / ".env")


def load_jsonl(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_jsonl(path, row):
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def get_attr(obj, name, default=0):
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(name, default)
    else:
        value = getattr(obj, name, default)
    return default if value is None else value


def usage_dict(resp):
    usage = getattr(resp, "usage", None)
    inp = int(get_attr(usage, "input_tokens", 0))
    out = int(get_attr(usage, "output_tokens", 0))
    total = int(get_attr(usage, "total_tokens", inp + out))

    input_details = get_attr(usage, "input_tokens_details", None)
    cached = int(get_attr(input_details, "cached_tokens", 0))

    output_details = get_attr(usage, "output_tokens_details", None)
    reasoning = int(get_attr(output_details, "reasoning_tokens", 0))

    return {
        "input_tokens": inp,
        "cached_input_tokens": cached,
        "uncached_input_tokens": max(inp - cached, 0),
        "output_tokens": out,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-5.6-terra")
    ap.add_argument(
        "--input",
        default=str(HERE / "eval_inputs_location_time_v1.jsonl")
    )
    ap.add_argument(
        "--prompt",
        default=str(PROJECT_ROOT / "intent_parser_prompt_team_v1.txt")
    )
    ap.add_argument(
        "--schema",
        default=str(PROJECT_ROOT / "user_intent_schema_team_v1.json")
    )
    ap.add_argument(
        "--output",
        default=str(HERE / "predictions_location_time_v1.jsonl")
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.15)
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(
            "상위 프로젝트 폴더의 .env에 OPENAI_API_KEY가 필요합니다."
        )

    rows = load_jsonl(args.input)
    if args.limit:
        rows = rows[:args.limit]

    output = Path(args.output)
    if args.overwrite and output.exists():
        output.unlink()

    prompt = Path(args.prompt).read_text(encoding="utf-8")
    schema = Path(args.schema).read_text(encoding="utf-8")
    instructions = prompt + "\n\n# 실제 평가 JSON Schema\n" + schema

    client = OpenAI()

    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }

    print("=" * 72)
    print("Location & Time Scope Test V1")
    print(f"Model              : {args.model}")
    print(f"Requests           : {len(rows)}")
    print("Reasoning effort   : none")
    print("Project root       :", PROJECT_ROOT)
    print("=" * 72)

    for idx, row in enumerate(rows, 1):
        print(f"[{idx:02d}/{len(rows)}] #{row['test_id']} {row['input']}")

        predicted = None
        raw = ""
        err = None
        usage = {k: 0 for k in totals}

        try:
            resp = client.responses.create(
                model=args.model,
                instructions=instructions,
                input=(
                    "Return exactly one valid JSON object only. "
                    "Follow the supplied JSON Schema exactly. "
                    "Do not use Markdown or explanations.\n\n"
                    f"User request:\n{row['input']}"
                ),
                text={"format": {"type": "json_object"}},
                reasoning={"effort": "none"},
                prompt_cache_key="intent-parser-team-v1-location-time-v1",
                max_output_tokens=500,
            )

            raw = resp.output_text.strip()
            obj = json.loads(raw)
            predicted = obj if isinstance(obj, dict) else None

            if predicted is None:
                err = "JSON root is not an object"

            usage = usage_dict(resp)

        except Exception as e:
            err = f"{type(e).__name__}: {e}"

        for key in totals:
            totals[key] += usage[key]

        append_jsonl(output, {
            "test_id": row["test_id"],
            "input": row["input"],
            "predicted": predicted,
            "raw_output": raw,
            "api_error": err,
            "usage": usage,
        })

        if err:
            print("   -> ERROR:", err)
        else:
            cache_rate = (
                usage["cached_input_tokens"] / usage["input_tokens"] * 100
                if usage["input_tokens"] else 0
            )
            print(
                f"   -> OK | total={usage['total_tokens']} "
                f"| cached={cache_rate:.1f}%"
            )

        time.sleep(args.sleep)

    cache_rate = (
        totals["cached_input_tokens"] / totals["input_tokens"]
        if totals["input_tokens"] else 0
    )

    usage_summary = {
        **totals,
        "cache_rate": cache_rate,
        "requests": len(rows),
        "average_total_tokens_per_request": (
            totals["total_tokens"] / len(rows) if rows else 0
        ),
    }

    usage_path = HERE / "location_time_v1_usage_summary.json"
    usage_path.write_text(
        json.dumps(usage_summary, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\nTOKEN USAGE")
    print(json.dumps(usage_summary, ensure_ascii=False, indent=2))
    print("\n다음 평가:")
    print(
        'python Location_Time_Scope_Test_V1\\evaluate_location_time_v1.py '
        'Location_Time_Scope_Test_V1\\predictions_location_time_v1.jsonl'
    )


if __name__ == "__main__":
    main()
