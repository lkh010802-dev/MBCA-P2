#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, csv, json
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent

def load_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]

def f1_sets(expected, predicted):
    a, b = set(expected), set(predicted)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    tp = len(a & b)
    p = tp / len(b)
    r = tp / len(a)
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions")
    ap.add_argument("--golden", default=str(HERE / "golden_tests_robustness_v1.jsonl"))
    ap.add_argument("--schema", default=str(HERE / "user_intent_schema_team_v1.json"))
    ap.add_argument("--out-dir", default="evaluation_result_robustness_v1")
    args = ap.parse_args()

    gold = {x["test_id"]: x for x in load_jsonl(args.golden)}
    preds = {x["test_id"]: x for x in load_jsonl(args.predictions)}
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    scalar_fields = [
        "start_location_text", "end_location_text", "start_time", "end_time",
        "desired_duration_minutes", "transport_mode", "budget_max",
        "budget_preference", "space_preference"
    ]
    defaults = {
        "start_location_text": None,
        "end_location_text": None,
        "start_time": None,
        "end_time": None,
        "desired_duration_minutes": None,
        "transport_mode": "auto",
        "budget_max": None,
        "budget_preference": None,
        "space_preference": None,
    }

    field_hits = Counter()
    field_total = Counter()
    failures = Counter()
    rows = []
    exact = 0
    schema_valid = 0
    activity_f1s = []
    companion_f1s = []
    default_hallucinations = 0
    default_opportunities = 0

    category_total = Counter()
    category_exact = Counter()

    for tid in sorted(gold):
        g = gold[tid]
        category = g.get("category", "uncategorized")
        category_total[category] += 1

        prow = preds.get(tid, {})
        p = prow.get("predicted")
        errors = []

        if not isinstance(p, dict):
            errors.append("MISSING_PREDICTION")
            p = {}

        schema_errors = list(validator.iter_errors(p)) if p else []
        if schema_errors:
            errors.append("SCHEMA_INVALID")
        else:
            schema_valid += 1

        expected = g["expected"]

        for f in scalar_fields:
            field_total[f] += 1
            if p.get(f) == expected.get(f):
                field_hits[f] += 1
            else:
                errors.append(f"{f.upper()}_MISMATCH")

        af1 = f1_sets(expected.get("activities", []), p.get("activities", []))
        cf1 = f1_sets(expected.get("companions", []), p.get("companions", []))
        activity_f1s.append(af1)
        companion_f1s.append(cf1)

        if af1 < 1:
            errors.append("ACTIVITY_MISMATCH")
        if cf1 < 1:
            errors.append("COMPANION_MISMATCH")

        for f, default in defaults.items():
            if expected.get(f) == default:
                default_opportunities += 1
                if p.get(f) != default:
                    default_hallucinations += 1

        if expected.get("activities", []) == []:
            default_opportunities += 1
            if p.get("activities", []) != []:
                default_hallucinations += 1

        if expected.get("companions", []) == []:
            default_opportunities += 1
            if p.get("companions", []) != []:
                default_hallucinations += 1

        unique_errors = list(dict.fromkeys(errors))
        passed = len(unique_errors) == 0
        if passed:
            exact += 1
            category_exact[category] += 1
        else:
            failures.update(unique_errors)

        rows.append({
            "test_id": tid,
            "category": category,
            "input": g["input"],
            "result": "PASS" if passed else "FAIL",
            "errors": "|".join(unique_errors) if unique_errors else "PASS",
            "activity_f1": round(af1, 3),
            "companion_f1": round(cf1, 3),
            "expected_json": json.dumps(expected, ensure_ascii=False),
            "predicted_json": json.dumps(p, ensure_ascii=False),
        })

    n = len(gold)
    category_accuracy = {
        c: {
            "passes": category_exact[c],
            "cases": category_total[c],
            "accuracy": category_exact[c] / category_total[c],
        }
        for c in sorted(category_total)
    }

    summary = {
        "test_suite": "Robustness Test V1",
        "cases_expected": n,
        "cases_received": len(preds),
        "schema_validity": schema_valid / n if n else 0,
        "exact_case_accuracy": exact / n if n else 0,
        "activity_f1": sum(activity_f1s) / n if n else 0,
        "companions_f1": sum(companion_f1s) / n if n else 0,
        "default_hallucination_rate": (
            default_hallucinations / default_opportunities
            if default_opportunities else 0
        ),
        "field_accuracy": {
            f: field_hits[f] / field_total[f] if field_total[f] else 0
            for f in scalar_fields
        },
        "category_accuracy": category_accuracy,
        "failure_type_counts": dict(failures),
        "recommended_gates": {
            "schema_validity": ">= 1.00",
            "exact_case_accuracy": ">= 0.88",
            "activity_f1": ">= 0.95",
            "companions_f1": ">= 0.95",
            "default_hallucination_rate": "< 0.03",
            "category_accuracy": "각 category >= 0.67 (초기 탐색용)"
        }
    }

    (out / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (out / "evaluation_cases.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    html = [
        '<!doctype html><meta charset="utf-8"><title>Robustness Test V1</title>',
        '<style>body{font-family:Arial,Malgun Gothic,sans-serif;max-width:1200px;margin:30px auto;padding:0 14px}'
        'table{border-collapse:collapse;width:100%;margin:15px 0 28px}th,td{border:1px solid #ddd;padding:7px;vertical-align:top}'
        'th{background:#17365D;color:white}pre{background:#f5f5f5;padding:12px;overflow:auto}</style>',
        '<h1>Robustness Test V1 Evaluation</h1>',
        '<h2>Summary</h2><pre>' + json.dumps(summary, ensure_ascii=False, indent=2) + '</pre>',
        '<h2>Category Accuracy</h2><table><tr><th>Category</th><th>Pass</th><th>Cases</th><th>Accuracy</th></tr>'
    ]
    for c, v in category_accuracy.items():
        html.append(
            f"<tr><td>{c}</td><td>{v['passes']}</td><td>{v['cases']}</td>"
            f"<td>{v['accuracy']*100:.1f}%</td></tr>"
        )
    html.append('</table><h2>Cases</h2><table><tr><th>ID</th><th>Category</th><th>Input</th><th>Result</th><th>Errors</th></tr>')
    for r in rows:
        html.append(
            f"<tr><td>{r['test_id']}</td><td>{r['category']}</td><td>{r['input']}</td>"
            f"<td>{r['result']}</td><td>{r['errors']}</td></tr>"
        )
    html.append("</table>")
    (out / "evaluation_report.html").write_text("".join(html), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
