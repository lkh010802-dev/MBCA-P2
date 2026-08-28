#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
    input_tokens = int(get_attr(usage, "input_tokens", 0))
    output_tokens = int(get_attr(usage, "output_tokens", 0))
    total_tokens = int(get_attr(usage, "total_tokens", input_tokens + output_tokens))

    in_details = get_attr(usage, "input_tokens_details", None)
    cached = int(get_attr(in_details, "cached_tokens", 0))

    out_details = get_attr(usage, "output_tokens_details", None)
    reasoning = int(get_attr(out_details, "reasoning_tokens", 0))

    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "uncached_input_tokens": max(input_tokens - cached, 0),
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": total_tokens,
    }


def default_runtime_context():
    tz = "Asia/Seoul"
    now = datetime.now(ZoneInfo(tz))
    return {
        "current_datetime": now.isoformat(timespec="minutes"),
        "timezone": tz,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-5.6-terra")
    ap.add_argument("--input", required=True)
    ap.add_argument("--prompt", default=str(HERE / "intent_parser_prompt_team_v1_1_FINAL.txt"))
    ap.add_argument("--schema", default=str(HERE / "user_intent_schema_team_v1_1.json"))
    ap.add_argument("--output", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.15)
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(".env에 OPENAI_API_KEY가 필요합니다.")

    rows = load_jsonl(args.input)
    if args.limit:
        rows = rows[:args.limit]

    output = Path(args.output)
    if args.overwrite and output.exists():
        output.unlink()

    prompt = Path(args.prompt).read_text(encoding="utf-8")
    schema_text = Path(args.schema).read_text(encoding="utf-8")
    instructions = prompt + "\n\n# 실제 평가 JSON Schema\n" + schema_text

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
    print("TeamSpec V1.1 Evaluation Runner")
    print("Model            :", args.model)
    print("Requests         :", len(rows))
    print("Reasoning effort : none")
    print("=" * 72)

    for idx, row in enumerate(rows, 1):
        context = row.get("runtime_context") or default_runtime_context()

        print(f"[{idx:02d}/{len(rows)}] #{row['test_id']} {row['input']}")
        print(
            "   context:",
            context.get("current_datetime"),
            context.get("timezone"),
        )

        predicted = None
        raw = ""
        error = None
        usage = {k: 0 for k in totals}

        try:
            response = client.responses.create(
                model=args.model,
                instructions=instructions,
                input=[
                    {
                        "role": "developer",
                        "content": (
                            "Runtime context for this request:\n"
                            + json.dumps(context, ensure_ascii=False)
                            + "\nUse it only when required to interpret relative time."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Return exactly one valid JSON object only. "
                            "Follow the provided JSON Schema exactly. "
                            "Do not use Markdown or explanations.\n\n"
                            f"User request:\n{row['input']}"
                        ),
                    },
                ],
                text={"format": {"type": "json_object"}},
                reasoning={"effort": "none"},
                prompt_cache_key="intent-parser-team-v1-1",
                max_output_tokens=500,
            )

            raw = response.output_text.strip()
            obj = json.loads(raw)
            predicted = obj if isinstance(obj, dict) else None
            if predicted is None:
                error = "JSON root is not an object"

            usage = usage_dict(response)

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        for key in totals:
            totals[key] += usage[key]

        append_jsonl(
            output,
            {
                "test_id": row["test_id"],
                "input": row["input"],
                "runtime_context": context,
                "predicted": predicted,
                "raw_output": raw,
                "api_error": error,
                "usage": usage,
            },
        )

        if error:
            print("   -> ERROR:", error)
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

    usage_path = output.with_name(output.stem + "_usage_summary.json")
    usage_path.write_text(
        json.dumps(usage_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nTOKEN USAGE")
    print(json.dumps(usage_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
