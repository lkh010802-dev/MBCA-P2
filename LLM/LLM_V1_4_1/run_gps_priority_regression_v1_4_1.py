#!/usr/bin/env python3
"""Live integration checks for explicit start text versus request GPS fallback."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CASES_PATH = HERE / "gps_priority_cases_v1_4_1.json"
REPORT_PATH = HERE / "gps_priority_report_v1_4_1.json"
SET_LIKE_FIELDS = {"activities", "companions"}


def field_equal(field, expected, actual):
    if field in SET_LIKE_FIELDS:
        return set(expected or []) == set(actual or [])
    return expected == actual


def compare_subset(expected, actual):
    return {
        field: {"expected": value, "actual": actual.get(field)}
        for field, value in expected.items()
        if not field_equal(field, value, actual.get(field))
    }


def main():
    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not configured", file=sys.stderr)
        return 2

    sys.path.insert(0, str(REPO_ROOT))
    from conditions import resolve_start_location
    from models import RecommendRequest, StructuredConditions
    from intent_parser import parse_intent

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []
    passed = 0

    for index, case in enumerate(cases, 1):
        gps = case["gps"]
        debug = parse_intent(
            case["text"],
            runtime_context={
                "current_datetime": case["current_datetime"],
                "timezone": "Asia/Seoul",
            },
            include_debug=True,
        )
        intent = debug["intent"]
        request = RecommendRequest(
            user_message=case["text"],
            gps_latitude=gps["latitude"],
            gps_longitude=gps["longitude"],
        )
        resolved_start = resolve_start_location(request, StructuredConditions(**intent))

        intent_mismatches = compare_subset(case["expect_intent"], intent)
        start_mismatches = compare_subset(case["expect_start"], resolved_start)
        ok = not intent_mismatches and not start_mismatches
        passed += int(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {index:02d}/{len(cases)} {case['id']}")
        if intent_mismatches:
            print("  intent=" + json.dumps(intent_mismatches, ensure_ascii=False))
        if start_mismatches:
            print("  resolved_start=" + json.dumps(start_mismatches, ensure_ascii=False))

        results.append(
            {
                "id": case["id"],
                "text": case["text"],
                "gps": gps,
                "llm_intent": debug["llm_intent"],
                "intent": intent,
                "postprocess_changes": debug["postprocess_changes"],
                "resolved_start": resolved_start,
                "intent_mismatches": intent_mismatches,
                "start_mismatches": start_mismatches,
                "runtime": debug["runtime"],
            }
        )

    report = {
        "summary": {"passed": passed, "total": len(cases)},
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gps priority: {passed}/{len(cases)} PASS")
    print(f"report: {REPORT_PATH}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
