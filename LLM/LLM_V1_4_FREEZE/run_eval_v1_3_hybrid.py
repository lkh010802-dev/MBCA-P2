#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from intent_postprocess import postprocess_intent

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")


def load_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


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
    cache_write = int(get_attr(in_details, "cache_write_tokens", 0))

    out_details = get_attr(usage, "output_tokens_details", None)
    reasoning = int(get_attr(out_details, "reasoning_tokens", 0))

    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": cache_write,
        "uncached_nonwrite_input_tokens": max(input_tokens - cached - cache_write, 0),
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": total_tokens,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--prompt", default=str(HERE / "intent_parser_prompt_team_v1_3_COST_OPT.txt"))
    ap.add_argument("--schema", default=str(HERE / "user_intent_schema_team_v1_3_STRICT.json"))
    ap.add_argument("--cache-key", default="intent-parser-team-v1-3-16field-cost-opt")
    ap.add_argument("--cache-ttl", default="30m")
    ap.add_argument("--max-output-tokens", type=int, default=300)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.15)
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(".env에 OPENAI_API_KEY가 필요합니다.")

    rows = load_jsonl(args.input)
    if args.limit:
        rows = rows[:args.limit]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.overwrite and output.exists():
        output.unlink()

    prompt = Path(args.prompt).read_text(encoding="utf-8")
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    client = OpenAI()

    total = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "uncached_nonwrite_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }

    for idx, row in enumerate(rows, 1):
        context = row.get("runtime_context") or {}
        raw = ""
        predicted = None
        llm_predicted = None
        postprocess_changes = []
        error = None
        usage = {k: 0 for k in total}

        try:
            response = client.responses.create(
                model=args.model,
                input=[
                    {
                        "role": "developer",
                        "content": [
                            {
                                "type": "input_text",
                                "text": prompt,
                                "prompt_cache_breakpoint": {"mode": "explicit"},
                            }
                        ],
                    },
                    {
                        "role": "developer",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Runtime Context (output field가 아님; 상대시간 계산에만 사용):\n"
                                    + json.dumps(context, ensure_ascii=False)
                                ),
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": row["input"]}],
                    },
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
                prompt_cache_key=args.cache_key,
                prompt_cache_options={"mode": "explicit", "ttl": args.cache_ttl},
                max_output_tokens=args.max_output_tokens,
            )

            raw = response.output_text.strip()
            obj = json.loads(raw)
            llm_predicted = obj if isinstance(obj, dict) else None
            predicted = llm_predicted
            postprocess_changes = []
            if predicted is None:
                error = "JSON root is not an object"
            else:
                predicted, postprocess_changes = postprocess_intent(
                    row["input"], context, predicted
                )
            usage = usage_dict(response)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        for key in total:
            total[key] += usage[key]

        append_jsonl(output, {
            "test_id": row["test_id"],
            "input": row["input"],
            "runtime_context": context,
            "llm_predicted": llm_predicted,
            "predicted": predicted,
            "postprocess_changes": postprocess_changes,
            "raw_output": raw,
            "api_error": error,
            "usage": usage,
        })

        cache_rate = usage["cached_input_tokens"] / usage["input_tokens"] if usage["input_tokens"] else 0
        print(f"[{idx:02d}/{len(rows)}] #{row['test_id']} "
              f"{'ERROR '+error if error else 'OK'} | "
              f"in={usage['input_tokens']} cached={cache_rate:.1%} "
              f"write={usage['cache_write_input_tokens']} out={usage['output_tokens']}")
        time.sleep(args.sleep)

    summary = {
        **total,
        "requests": len(rows),
        "cache_read_rate": total["cached_input_tokens"] / total["input_tokens"] if total["input_tokens"] else 0,
        "average_input_tokens_per_request": total["input_tokens"] / len(rows) if rows else 0,
        "average_output_tokens_per_request": total["output_tokens"] / len(rows) if rows else 0,
    }
    usage_path = output.with_name(output.stem + "_usage_summary.json")
    usage_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
