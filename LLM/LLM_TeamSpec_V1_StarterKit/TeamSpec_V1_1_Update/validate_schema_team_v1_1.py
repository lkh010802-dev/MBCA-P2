#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent

schema = json.loads(
    (HERE / "user_intent_schema_team_v1_1.json").read_text(encoding="utf-8")
)
rows = [
    json.loads(line)
    for line in (HERE / "golden_tests_50_team_v1_1.jsonl")
        .read_text(encoding="utf-8").splitlines()
    if line.strip()
]

validator = Draft202012Validator(schema)
errors = []

for row in rows:
    row_errors = list(validator.iter_errors(row["expected"]))
    if row_errors:
        errors.append({
            "test_id": row["test_id"],
            "errors": [e.message for e in row_errors],
        })

print(f"Golden cases: {len(rows)}")
print(f"Schema valid: {len(rows) - len(errors)}/{len(rows)}")

if errors:
    print(json.dumps(errors, ensure_ascii=False, indent=2))
    raise SystemExit(1)

print("PASS: TeamSpec V1.1 Golden 50 is schema-valid.")
