#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent


def load_jsonl(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def f1_sets(expected, predicted):
    a, b = set(expected), set(predicted)

    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    tp = len(a & b)
    precision = tp / len(b)
    recall = tp / len(a)

    return (
        0.0 if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions")
    ap.add_argument(
        "--golden",
        default=str(HERE / "golden_tests_location_time_v1.jsonl")
    )
    ap.add_argument(
        "--schema",
        default=str(PROJECT_ROOT / "user_intent_schema_team_v1.json")
    )
    ap.add_argument(
        "--out-dir",
        default=str(HERE / "evaluation_result_location_time_v1")
    )
    args = ap.parse_args()

    golden = {row["test_id"]: row for row in load_jsonl(args.golden)}
    predictions = {
        row["test_id"]: row for row in load_jsonl(args.predictions)
    }

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scalar_fields = [
        "start_location_text",
        "end_location_text",
        "start_time",
        "end_time",
        "desired_duration_minutes",
        "transport_mode",
        "budget_max",
        "budget_preference",
        "space_preference",
    ]

    field_hits = Counter()
    field_total = Counter()
    failure_counts = Counter()

    category_total = Counter()
    category_exact = Counter()

    rows = []
    exact = 0
    schema_valid = 0
    activity_f1s = []
    companion_f1s = []

    for test_id in sorted(golden):
        g = golden[test_id]
        expected = g["expected"]
        category = g["category"]

        category_total[category] += 1

        p_row = predictions.get(test_id, {})
        predicted = p_row.get("predicted")

        errors = []

        if not isinstance(predicted, dict):
            predicted = {}
            errors.append("MISSING_PREDICTION")

        schema_errors = list(validator.iter_errors(predicted)) if predicted else []

        if schema_errors:
            errors.append("SCHEMA_INVALID")
        else:
            schema_valid += 1

        for field in scalar_fields:
            field_total[field] += 1
            if predicted.get(field) == expected.get(field):
                field_hits[field] += 1
            else:
                errors.append(field.upper() + "_MISMATCH")

        activity_f1 = f1_sets(
            expected.get("activities", []),
            predicted.get("activities", [])
        )
        companion_f1 = f1_sets(
            expected.get("companions", []),
            predicted.get("companions", [])
        )

        activity_f1s.append(activity_f1)
        companion_f1s.append(companion_f1)

        if activity_f1 < 1:
            errors.append("ACTIVITY_MISMATCH")

        if companion_f1 < 1:
            errors.append("COMPANION_MISMATCH")

        errors = list(dict.fromkeys(errors))
        passed = len(errors) == 0

        if passed:
            exact += 1
            category_exact[category] += 1
        else:
            failure_counts.update(errors)

        rows.append({
            "test_id": test_id,
            "category": category,
            "input": g["input"],
            "result": "PASS" if passed else "FAIL",
            "errors": "|".join(errors) if errors else "PASS",
            "expected_json": json.dumps(expected, ensure_ascii=False),
            "predicted_json": json.dumps(predicted, ensure_ascii=False),
        })

    n = len(golden)

    category_accuracy = {
        category: {
            "passes": category_exact[category],
            "cases": category_total[category],
            "accuracy": category_exact[category] / category_total[category],
        }
        for category in sorted(category_total)
    }

    summary = {
        "test_suite": "Location & Time Scope Test V1",
        "cases_expected": n,
        "cases_received": len(predictions),
        "schema_validity": schema_valid / n if n else 0,
        "exact_case_accuracy": exact / n if n else 0,
        "activity_f1": sum(activity_f1s) / n if n else 0,
        "companions_f1": sum(companion_f1s) / n if n else 0,
        "field_accuracy": {
            field: field_hits[field] / field_total[field]
            if field_total[field] else 0
            for field in scalar_fields
        },
        "category_accuracy": category_accuracy,
        "failure_type_counts": dict(failure_counts),
        "recommended_gates": {
            "schema_validity": ">= 1.00",
            "exact_case_accuracy": ">= 0.88",
            "start_location_text": ">= 0.95",
            "end_location_text": ">= 0.95",
            "start_time": ">= 0.95",
            "end_time": ">= 0.95",
            "activity_f1": ">= 0.95",
            "companions_f1": ">= 0.95"
        }
    }

    (out_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    with (out_dir / "evaluation_cases.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    html = [
        '<!doctype html><meta charset="utf-8">',
        '<title>Location & Time Scope Test V1</title>',
        '<style>',
        'body{font-family:Arial,Malgun Gothic,sans-serif;max-width:1200px;margin:30px auto;padding:0 14px}',
        'table{border-collapse:collapse;width:100%;margin:15px 0 28px}',
        'th,td{border:1px solid #ddd;padding:7px;vertical-align:top}',
        'th{background:#17365D;color:white}',
        'pre{background:#f5f5f5;padding:12px;overflow:auto}',
        '</style>',
        '<h1>Location & Time Scope Test V1</h1>',
        '<h2>Summary</h2>',
        '<pre>' + json.dumps(summary, ensure_ascii=False, indent=2) + '</pre>',
        '<h2>Cases</h2>',
        '<table><tr><th>ID</th><th>Category</th><th>Input</th>',
        '<th>Result</th><th>Errors</th></tr>',
    ]

    for row in rows:
        html.append(
            f"<tr><td>{row['test_id']}</td>"
            f"<td>{row['category']}</td>"
            f"<td>{row['input']}</td>"
            f"<td>{row['result']}</td>"
            f"<td>{row['errors']}</td></tr>"
        )

    html.append("</table>")

    (out_dir / "evaluation_report.html").write_text(
        "".join(html), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
