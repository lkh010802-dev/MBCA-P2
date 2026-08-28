#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
space_preference 안정성 초경량 테스트

목적
- 기존 전체 50개를 반복 실행하지 않고,
  실패했던 3개 문장만 각각 N회 실행합니다.
- 기본값: 3문장 x 5회 = 총 15 API 요청
- space_preference 성공률과 실제 token usage를 집계합니다.
- input / cached input / output / reasoning / total token을 기록합니다.

필요 파일 (이 스크립트와 같은 폴더)
- .env
- intent_parser_prompt_team_v1.txt
- user_intent_schema_team_v1.json

설치
    pip install -U openai python-dotenv jsonschema

기본 실행
    python run_space_stability_test.py

모델 지정
    python run_space_stability_test.py --model gpt-5.6-terra

반복 횟수 변경
    python run_space_stability_test.py --repeats 3

저비용 모델로 개발 테스트
    python run_space_stability_test.py --model gpt-5.6-luna
"""

import argparse
import csv
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    raise SystemExit("python-dotenv 필요: pip install -U python-dotenv")

try:
    from openai import OpenAI
except ImportError:
    raise SystemExit("openai 필요: pip install -U openai")

try:
    from jsonschema import validate as schema_validate
    from jsonschema.exceptions import ValidationError
except ImportError:
    raise SystemExit("jsonschema 필요: pip install -U jsonschema")


HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")


TEST_CASES = [
    {
        "case_id": 9,
        "input": "실내에서 방탈출이나 보드게임 하고 싶어",
        "expected_space_preference": "indoor",
    },
    {
        "case_id": 41,
        "input": "야외에서 걷기 좋은 데 가고 싶어",
        "expected_space_preference": "outdoor",
    },
    {
        "case_id": 50,
        "input": "실내든 야외든 상관없이 아무거나 추천해줘",
        "expected_space_preference": "any",
    },
]


def get_attr(obj, name, default=0):
    """dict / SDK object 모두 안전하게 읽기."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(name, default)
    else:
        value = getattr(obj, name, default)
    return default if value is None else value


def extract_usage(resp):
    usage = getattr(resp, "usage", None)

    input_tokens = int(get_attr(usage, "input_tokens", 0))
    output_tokens = int(get_attr(usage, "output_tokens", 0))
    total_tokens = int(get_attr(usage, "total_tokens", input_tokens + output_tokens))

    input_details = get_attr(usage, "input_tokens_details", None)
    output_details = get_attr(usage, "output_tokens_details", None)

    cached_tokens = int(get_attr(input_details, "cached_tokens", 0))
    reasoning_tokens = int(get_attr(output_details, "reasoning_tokens", 0))

    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": max(input_tokens - cached_tokens, 0),
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
    }


def append_jsonl(path, row):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-5.6-terra")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument(
        "--prompt",
        default=str(HERE / "intent_parser_prompt_team_v1.txt"),
    )
    ap.add_argument(
        "--schema",
        default=str(HERE / "user_intent_schema_team_v1.json"),
    )
    ap.add_argument(
        "--out-dir",
        default=str(HERE / "space_stability_result"),
    )
    ap.add_argument(
        "--reasoning-effort",
        default="minimal",
        choices=["none", "minimal", "low", "medium", "high"],
    )
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--max-output-tokens", type=int, default=500)
    args = ap.parse_args()

    if args.repeats < 1:
        raise SystemExit("--repeats는 1 이상이어야 합니다.")

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(
            ".env에서 OPENAI_API_KEY를 찾지 못했습니다.\n"
            "예: OPENAI_API_KEY=sk-..."
        )

    prompt_path = Path(args.prompt)
    schema_path = Path(args.schema)

    if not prompt_path.exists():
        raise SystemExit(f"프롬프트 파일 없음: {prompt_path}")
    if not schema_path.exists():
        raise SystemExit(f"Schema 파일 없음: {schema_path}")

    prompt = prompt_path.read_text(encoding="utf-8")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    instructions = (
        prompt
        + "\n\n# 실제 평가 JSON Schema\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs_path = out_dir / "space_stability_runs.jsonl"
    csv_path = out_dir / "space_stability_cases.csv"
    summary_path = out_dir / "space_stability_summary.json"

    # 매 실행마다 새 결과로 시작
    for p in (runs_path, csv_path, summary_path):
        if p.exists():
            p.unlink()

    client = OpenAI()

    total_requests = len(TEST_CASES) * args.repeats

    print("=" * 72)
    print("space_preference 안정성 테스트")
    print(f"Model              : {args.model}")
    print(f"Cases              : {len(TEST_CASES)}")
    print(f"Repeats per case   : {args.repeats}")
    print(f"Total API requests : {total_requests}")
    print(f"Reasoning effort   : {args.reasoning_effort}")
    print(f"Max output tokens  : {args.max_output_tokens}")
    print("=" * 72)

    all_rows = []
    request_no = 0

    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }

    # 같은 긴 prompt/schema가 반복되므로 고정 cache key 사용
    cache_key = "intent-parser-team-v1-space-stability"

    for case in TEST_CASES:
        for repeat_no in range(1, args.repeats + 1):
            request_no += 1

            expected = case["expected_space_preference"]
            user_input = case["input"]

            print(
                f"[{request_no:02d}/{total_requests}] "
                f"case #{case['case_id']} repeat {repeat_no}/{args.repeats} "
                f"expected={expected}"
            )

            predicted = None
            predicted_space = None
            raw_output = ""
            api_error = None
            schema_valid = False
            usage_info = {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "uncached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
            }

            started = time.perf_counter()

            try:
                resp = client.responses.create(
                    model=args.model,
                    instructions=instructions,
                    input=(
                        "Return exactly one valid JSON object only. "
                        "Follow the supplied JSON Schema exactly. "
                        "Do not use Markdown or explanations.\n\n"
                        f"User request:\n{user_input}"
                    ),
                    text={"format": {"type": "json_object"}},
                    reasoning={"effort": args.reasoning_effort},
                    prompt_cache_key=cache_key,
                    max_output_tokens=args.max_output_tokens,
                )

                elapsed = time.perf_counter() - started

                raw_output = resp.output_text.strip()
                predicted = json.loads(raw_output)

                if not isinstance(predicted, dict):
                    raise ValueError("JSON root is not an object")

                try:
                    schema_validate(instance=predicted, schema=schema)
                    schema_valid = True
                except ValidationError:
                    schema_valid = False

                predicted_space = predicted.get("space_preference")
                usage_info = extract_usage(resp)

            except Exception as e:
                elapsed = time.perf_counter() - started
                api_error = f"{type(e).__name__}: {e}"

            for key in totals:
                totals[key] += usage_info[key]

            passed = (
                api_error is None
                and schema_valid
                and predicted_space == expected
            )

            row = {
                "request_no": request_no,
                "case_id": case["case_id"],
                "repeat_no": repeat_no,
                "input": user_input,
                "expected_space_preference": expected,
                "predicted_space_preference": predicted_space,
                "passed": passed,
                "schema_valid": schema_valid,
                "api_error": api_error,
                "elapsed_seconds": round(elapsed, 3),
                **usage_info,
                "predicted": predicted,
                "raw_output": raw_output,
            }

            all_rows.append(row)
            append_jsonl(runs_path, row)

            cache_pct = (
                usage_info["cached_input_tokens"] / usage_info["input_tokens"] * 100
                if usage_info["input_tokens"] else 0.0
            )

            if api_error:
                print(f"   -> ERROR: {api_error}")
            else:
                status = "PASS" if passed else "FAIL"
                print(
                    f"   -> {status} | got={predicted_space} "
                    f"| input={usage_info['input_tokens']} "
                    f"(cached={usage_info['cached_input_tokens']}, {cache_pct:.1f}%) "
                    f"| output={usage_info['output_tokens']} "
                    f"| reasoning={usage_info['reasoning_tokens']} "
                    f"| total={usage_info['total_tokens']}"
                )

            time.sleep(args.sleep)

    # CSV
    csv_fields = [
        "request_no",
        "case_id",
        "repeat_no",
        "input",
        "expected_space_preference",
        "predicted_space_preference",
        "passed",
        "schema_valid",
        "api_error",
        "elapsed_seconds",
        "input_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    ]

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: row.get(k) for k in csv_fields})

    # 케이스별 집계
    grouped = defaultdict(list)
    for row in all_rows:
        grouped[row["case_id"]].append(row)

    case_summaries = []

    for case in TEST_CASES:
        rows = grouped[case["case_id"]]
        success_count = sum(1 for r in rows if r["passed"])
        values = Counter(
            "null" if r["predicted_space_preference"] is None
            else str(r["predicted_space_preference"])
            for r in rows
            if r["api_error"] is None
        )

        case_summaries.append(
            {
                "case_id": case["case_id"],
                "input": case["input"],
                "expected": case["expected_space_preference"],
                "attempts": len(rows),
                "passes": success_count,
                "success_rate": success_count / len(rows) if rows else 0.0,
                "predicted_value_counts": dict(values),
            }
        )

    total_passes = sum(1 for r in all_rows if r["passed"])
    successful_api_calls = sum(1 for r in all_rows if r["api_error"] is None)
    schema_valid_calls = sum(1 for r in all_rows if r["schema_valid"])

    cache_rate = (
        totals["cached_input_tokens"] / totals["input_tokens"]
        if totals["input_tokens"]
        else 0.0
    )

    summary = {
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "cases": len(TEST_CASES),
        "repeats_per_case": args.repeats,
        "requests_planned": total_requests,
        "requests_completed": len(all_rows),
        "successful_api_calls": successful_api_calls,
        "schema_valid_calls": schema_valid_calls,
        "overall_passes": total_passes,
        "overall_success_rate": total_passes / len(all_rows) if all_rows else 0.0,
        "case_results": case_summaries,
        "token_usage": {
            **totals,
            "cache_rate": cache_rate,
            "average_total_tokens_per_request": (
                totals["total_tokens"] / len(all_rows) if all_rows else 0.0
            ),
        },
    }

    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("RESULT")
    print("=" * 72)

    for c in case_summaries:
        print(
            f"#{c['case_id']:>2} "
            f"{c['passes']}/{c['attempts']} "
            f"({c['success_rate'] * 100:.1f}%) "
            f"expected={c['expected']} "
            f"values={c['predicted_value_counts']}"
        )

    print("-" * 72)
    print(
        f"Overall            : {total_passes}/{len(all_rows)} "
        f"({summary['overall_success_rate'] * 100:.1f}%)"
    )
    print(f"API success        : {successful_api_calls}/{len(all_rows)}")
    print(f"Schema valid       : {schema_valid_calls}/{len(all_rows)}")
    print()
    print("TOKEN USAGE")
    print(f"Input tokens       : {totals['input_tokens']:,}")
    print(f"Cached input       : {totals['cached_input_tokens']:,}")
    print(f"Uncached input     : {totals['uncached_input_tokens']:,}")
    print(f"Cache rate         : {cache_rate * 100:.1f}%")
    print(f"Output tokens      : {totals['output_tokens']:,}")
    print(f"Reasoning tokens   : {totals['reasoning_tokens']:,}")
    print(f"Total tokens       : {totals['total_tokens']:,}")
    print(
        "Avg tokens/request : "
        f"{summary['token_usage']['average_total_tokens_per_request']:.1f}"
    )
    print()
    print("FILES")
    print(f"- {summary_path}")
    print(f"- {csv_path}")
    print(f"- {runs_path}")
    print("=" * 72)


if __name__ == "__main__":
    main()
