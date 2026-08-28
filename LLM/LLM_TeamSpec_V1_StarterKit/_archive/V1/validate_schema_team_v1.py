#!/usr/bin/env python3
import json, sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    raise SystemExit("jsonschema 필요: pip install -U jsonschema")
HERE=Path(__file__).resolve().parent
schema=json.loads((HERE/'user_intent_schema_team_v1.json').read_text(encoding='utf-8'))
if len(sys.argv)!=2:
    raise SystemExit('사용법: python validate_schema_team_v1.py output.json')
obj=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
errs=list(Draft202012Validator(schema).iter_errors(obj))
if not errs:
    print('PASS: Schema validation 통과')
    raise SystemExit(0)
print(f'FAIL: {len(errs)} errors')
for e in errs:
    p='.'.join(map(str,e.absolute_path)) or '<root>'
    print(f'- [{p}] {e.message}')
raise SystemExit(1)
