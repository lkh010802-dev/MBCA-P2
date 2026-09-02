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
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]

def f1_sets(expected, predicted):
    a, b = set(expected), set(predicted)
    if not a and not b: return 1.0
    if not a or not b: return 0.0
    tp = len(a & b)
    p, r = tp / len(b), tp / len(a)
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions")
    ap.add_argument("--golden", required=True)
    ap.add_argument("--schema", default=str(HERE / "user_intent_schema_team_v1_3_STRICT.json"))
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    golden = {x["test_id"]: x for x in load_jsonl(args.golden)}
    predictions = {x["test_id"]: x for x in load_jsonl(args.predictions)}
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)

    scalar_fields = [
        "start_location_text","target_location_text","target_location_scope","end_location_text","start_time","end_time",
        "start_time_period","end_time_period","desired_duration_min_minutes",
        "desired_duration_max_minutes","transport_mode","budget_max",
        "budget_preference","space_preference"
    ]
    field_hits, field_total, failure_counts = Counter(), Counter(), Counter()
    schema_valid = exact_cases = semantic_valid = 0
    activity_f1s, companion_f1s, rows = [], [], []

    for test_id in sorted(golden):
        g = golden[test_id]; expected = g["expected"]
        pred_row = predictions.get(test_id, {})
        predicted = pred_row.get("predicted")
        errors = []
        if not isinstance(predicted, dict):
            predicted = {}; errors.append("MISSING_PREDICTION")

        schema_errors = list(validator.iter_errors(predicted)) if predicted else []
        if schema_errors: errors.append("SCHEMA_INVALID")
        else: schema_valid += 1

        # V1.1 allOf/not 규칙은 Strict Structured Outputs에서 지원되지 않으므로 로컬에서 검사.
        if predicted.get("start_time") is not None and predicted.get("start_time_period") is not None:
            errors.append("START_TIME_PERIOD_CONFLICT")
        if predicted.get("end_time") is not None and predicted.get("end_time_period") is not None:
            errors.append("END_TIME_PERIOD_CONFLICT")
        target_text = predicted.get("target_location_text")
        target_scope = predicted.get("target_location_scope")
        if target_text is None and target_scope is not None:
            errors.append("TARGET_SCOPE_WITHOUT_LOCATION")
        if target_text is not None and target_scope is None:
            errors.append("TARGET_LOCATION_WITHOUT_SCOPE")
        dmin, dmax = predicted.get("desired_duration_min_minutes"), predicted.get("desired_duration_max_minutes")
        if dmin is not None and dmax is not None and dmin > dmax:
            errors.append("DURATION_RANGE_INVALID")
        activities = predicted.get("activities", [])
        companions = predicted.get("companions", [])
        if isinstance(activities, list) and len(activities) != len(set(activities)):
            errors.append("ACTIVITIES_DUPLICATE")
        if isinstance(companions, list) and len(companions) != len(set(companions)):
            errors.append("COMPANIONS_DUPLICATE")
        semantic_errors = (
            "START_TIME_PERIOD_CONFLICT", "END_TIME_PERIOD_CONFLICT",
            "TARGET_SCOPE_WITHOUT_LOCATION", "TARGET_LOCATION_WITHOUT_SCOPE",
            "DURATION_RANGE_INVALID", "ACTIVITIES_DUPLICATE", "COMPANIONS_DUPLICATE"
        )
        if not any(e in errors for e in semantic_errors):
            semantic_valid += 1

        for field in scalar_fields:
            field_total[field] += 1
            if predicted.get(field) == expected.get(field): field_hits[field] += 1
            else: errors.append(field.upper() + "_MISMATCH")

        af = f1_sets(expected.get("activities", []), predicted.get("activities", []))
        cf = f1_sets(expected.get("companions", []), predicted.get("companions", []))
        activity_f1s.append(af); companion_f1s.append(cf)
        if af < 1: errors.append("ACTIVITY_MISMATCH")
        if cf < 1: errors.append("COMPANION_MISMATCH")

        errors = list(dict.fromkeys(errors))
        if not errors: exact_cases += 1
        else: failure_counts.update(errors)

        rows.append({
            "test_id": test_id, "input": g["input"],
            "result": "PASS" if not errors else "FAIL",
            "errors": "|".join(errors) if errors else "PASS",
            "expected_json": json.dumps(expected, ensure_ascii=False),
            "predicted_json": json.dumps(predicted, ensure_ascii=False),
        })

    n = len(golden)
    summary = {
        "cases_expected": n,
        "cases_received": len(predictions),
        "schema_validity": schema_valid/n if n else 0,
        "semantic_invariant_validity": semantic_valid/n if n else 0,
        "exact_case_accuracy": exact_cases/n if n else 0,
        "activity_f1": sum(activity_f1s)/n if n else 0,
        "companions_f1": sum(companion_f1s)/n if n else 0,
        "field_accuracy": {f: field_hits[f]/field_total[f] for f in scalar_fields},
        "failure_type_counts": dict(failure_counts),
    }
    (out/"evaluation_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    with (out/"evaluation_cases.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
