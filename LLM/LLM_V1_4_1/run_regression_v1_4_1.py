#!/usr/bin/env python3
"""Run the V1.4.1 16-field live regression set and save a JSON report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
FIELDS = (
    "start_location_text",
    "target_location_text",
    "target_location_scope",
    "end_location_text",
    "start_time",
    "end_time",
    "start_time_period",
    "end_time_period",
    "desired_duration_min_minutes",
    "desired_duration_max_minutes",
    "activities",
    "transport_mode",
    "companions",
    "budget_max",
    "budget_preference",
    "space_preference",
)
DEFAULT_EXPECTED = {
    "start_location_text": None,
    "target_location_text": None,
    "target_location_scope": None,
    "end_location_text": None,
    "start_time": None,
    "end_time": None,
    "start_time_period": None,
    "end_time_period": None,
    "desired_duration_min_minutes": None,
    "desired_duration_max_minutes": None,
    "activities": [],
    "transport_mode": "auto",
    "companions": [],
    "budget_max": None,
    "budget_preference": None,
    "space_preference": None,
}
SET_LIKE_FIELDS = {"activities", "companions"}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=HERE / "regression_cases_v1_4_1.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=HERE / "regression_report_v1_4_1.json",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def load_cases(path: Path):
    cases = json.loads(path.read_text(encoding="utf-8"))
    ids = [case["id"] for case in cases]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate case ids: {duplicates}")

    for case in cases:
        unknown = set(case.get("expect", {})) - set(FIELDS)
        if unknown:
            raise ValueError(f"{case['id']}: unknown expected fields: {sorted(unknown)}")
    return cases


def expected_for(case):
    expected = dict(DEFAULT_EXPECTED)
    expected.update(case.get("expect", {}))
    return expected


def compare(expected, actual):
    mismatches = {}
    for field in FIELDS:
        expected_value = expected[field]
        actual_value = actual.get(field)
        if field in SET_LIKE_FIELDS:
            equal = (
                len(actual_value or []) == len(set(actual_value or []))
                and set(expected_value) == set(actual_value or [])
            )
        else:
            equal = expected_value == actual_value
        if not equal:
            mismatches[field] = {"expected": expected_value, "actual": actual_value}
    return mismatches


def main():
    args = parse_args()
    cases = load_cases(args.cases)
    categories = Counter(case["category"] for case in cases)
    print(f"validated {len(cases)} cases across {len(categories)} categories")
    if args.validate_only:
        print(json.dumps(dict(sorted(categories.items())), ensure_ascii=False))
        return 0

    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not configured", file=sys.stderr)
        return 2

    from intent_parser import parse_intent

    results = []
    passed = 0
    field_total = len(cases) * len(FIELDS)
    field_passed = 0

    for index, case in enumerate(cases, 1):
        expected = expected_for(case)
        try:
            debug = parse_intent(
                case["text"],
                case.get("runtime_context", {}),
                include_debug=True,
            )
            actual = debug["intent"]
            mismatches = compare(expected, actual)
            error = None
        except Exception as exc:
            debug = None
            actual = None
            mismatches = {"<execution>": {"expected": "success", "actual": repr(exc)}}
            error = repr(exc)

        case_field_passed = len(FIELDS) - sum(1 for key in mismatches if key in FIELDS)
        field_passed += case_field_passed
        ok = not mismatches
        passed += int(ok)
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {index:02d}/{len(cases)} {case['id']}")
        if mismatches:
            print("  " + json.dumps(mismatches, ensure_ascii=False))

        results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "text": case["text"],
                "runtime_context": case.get("runtime_context", {}),
                "expected": expected,
                "actual": actual,
                "mismatches": mismatches,
                "error": error,
                "debug": debug,
            }
        )

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "summary": {
            "case_passed": passed,
            "case_total": len(cases),
            "field_passed": field_passed,
            "field_total": field_total,
            "categories": dict(sorted(categories.items())),
        },
        "results": results,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"cases: {passed}/{len(cases)} PASS")
    print(f"fields: {field_passed}/{field_total} PASS")
    print(f"report: {args.report}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
