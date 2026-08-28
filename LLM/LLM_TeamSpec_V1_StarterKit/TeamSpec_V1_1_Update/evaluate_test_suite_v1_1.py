#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent


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
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions")
    ap.add_argument("--golden", required=True)
    ap.add_argument("--schema", default=str(HERE / "user_intent_schema_team_v1_1.json"))
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    golden = {x["test_id"]: x for x in load_jsonl(args.golden)}
    predictions = {x["test_id"]: x for x in load_jsonl(args.predictions)}

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    scalar_fields = [
        "start_location_text",
        "end_location_text",
        "start_time",
        "end_time",
        "start_time_period",
        "end_time_period",
        "desired_duration_min_minutes",
        "desired_duration_max_minutes",
        "transport_mode",
        "budget_max",
        "budget_preference",
        "space_preference",
    ]

    defaults = {
        "start_location_text": None,
        "end_location_text": None,
        "start_time": None,
        "end_time": None,
        "start_time_period": None,
        "end_time_period": None,
        "desired_duration_min_minutes": None,
        "desired_duration_max_minutes": None,
        "transport_mode": "auto",
        "budget_max": None,
        "budget_preference": None,
        "space_preference": None,
    }

    field_hits = Counter()
    field_total = Counter()
    failure_counts = Counter()

    schema_valid = 0
    exact_cases = 0
    activity_f1s = []
    companion_f1s = []
    default_hallucinations = 0
    default_opportunities = 0
    rows = []

    for test_id in sorted(golden):
        g = golden[test_id]
        expected = g["expected"]

        pred_row = predictions.get(test_id, {})
        predicted = pred_row.get("predicted")

        errors = []

        if not isinstance(predicted, dict):
            predicted = {}
            errors.append("MISSING_PREDICTION")

        schema_errors = list(validator.iter_errors(predicted)) if predicted else []
        if schema_errors:
            errors.append("SCHEMA_INVALID")
        else:
            schema_valid += 1

        # Semantic duration range validation.
        dmin = predicted.get("desired_duration_min_minutes")
        dmax = predicted.get("desired_duration_max_minutes")
        if dmin is not None and dmax is not None and dmin > dmax:
            errors.append("DURATION_RANGE_INVALID")

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

        for field, default in defaults.items():
            if expected.get(field) == default:
                default_opportunities += 1
                if predicted.get(field) != default:
                    default_hallucinations += 1

        if expected.get("activities", []) == []:
            default_opportunities += 1
            if predicted.get("activities", []) != []:
                default_hallucinations += 1

        if expected.get("companions", []) == []:
            default_opportunities += 1
            if predicted.get("companions", []) != []:
                default_hallucinations += 1

        errors = list(dict.fromkeys(errors))
        passed = not errors

        if passed:
            exact_cases += 1
        else:
            failure_counts.update(errors)

        rows.append({
            "test_id": test_id,
            "input": g["input"],
            "result": "PASS" if passed else "FAIL",
            "errors": "|".join(errors) if errors else "PASS",
            "activity_f1": round(activity_f1, 3),
            "companion_f1": round(companion_f1, 3),
            "expected_json": json.dumps(expected, ensure_ascii=False),
            "predicted_json": json.dumps(predicted, ensure_ascii=False),
        })

    n = len(golden)

    summary = {
        "test_suite": "TeamSpec V1.1 Custom Suite",
        "cases_expected": n,
        "cases_received": len(predictions),
        "schema_validity": schema_valid / n if n else 0,
        "exact_case_accuracy": exact_cases / n if n else 0,
        "activity_f1": sum(activity_f1s) / n if n else 0,
        "companions_f1": sum(companion_f1s) / n if n else 0,
        "default_hallucination_rate": (
            default_hallucinations / default_opportunities
            if default_opportunities else 0
        ),
        "field_accuracy": {
            field: field_hits[field] / field_total[field]
            if field_total[field] else 0
            for field in scalar_fields
        },
        "failure_type_counts": dict(failure_counts),
        "recommended_gates": {
            "schema_validity": ">= 1.00",
            "exact_case_accuracy": ">= 0.90",
            "activity_f1": ">= 0.95",
            "companions_f1": ">= 0.95",
            "default_hallucination_rate": "< 0.02",
        },
    }

    (out / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (out / "evaluation_cases.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
