#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent

schema_path = HERE / "user_intent_schema_team_v1.json"
golden_path = HERE / "golden_tests_robustness_v1.jsonl"

schema = json.loads(schema_path.read_text(encoding="utf-8"))
validator = Draft202012Validator(schema)

rows = [
    json.loads(x)
    for x in golden_path.read_text(encoding="utf-8").splitlines()
    if x.strip()
]

errors = []
for row in rows:
    es = list(validator.iter_errors(row["expected"]))
    if es:
        errors.append({
            "test_id": row["test_id"],
            "errors": [e.message for e in es]
        })

print(f"Golden cases: {len(rows)}")
print(f"Schema valid: {len(rows)-len(errors)}/{len(rows)}")

if errors:
    print(json.dumps(errors, ensure_ascii=False, indent=2))
    raise SystemExit(1)

print("PASS: Robustness V1 Golden answers are all schema-valid.")
