#!/usr/bin/env python3
# Run from the V1.3/V1.3.1 package root after copying this patch's intent_postprocess.py there.
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from intent_postprocess import postprocess_intent
HERE=Path(__file__).resolve().parent
SETS=[
 ('golden50', HERE/'tests/regression/golden50/golden.jsonl'),
 ('robustness30', HERE/'tests/regression/robustness30/golden.jsonl'),
 ('blind100_migrated', HERE/'tests/expansion/blind100_migrated/golden.jsonl'),
 ('target_location30', HERE/'tests/focus/target_location30/golden.jsonl'),
]
schema=json.loads((HERE/'user_intent_schema_team_v1_3_STRICT.json').read_text(encoding='utf-8'))
v=Draft202012Validator(schema)
summary={'total':0,'schema_invalid':0,'semantic_invalid':0,'postprocess_changed_correct':0,'sets':{}}
for name,path in SETS:
    rows=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
    stat={'cases':len(rows),'schema_invalid':0,'semantic_invalid':0,'postprocess_changed_correct':0}
    for r in rows:
        e=r['expected']; summary['total']+=1
        if list(v.iter_errors(e)):
            stat['schema_invalid']+=1; summary['schema_invalid']+=1
        t,s=e.get('target_location_text'),e.get('target_location_scope')
        if (t is None)!=(s is None):
            stat['semantic_invalid']+=1; summary['semantic_invalid']+=1
        pp,_=postprocess_intent(r['input'],r.get('runtime_context') or {},e)
        if pp!=e:
            stat['postprocess_changed_correct']+=1; summary['postprocess_changed_correct']+=1
    summary['sets'][name]=stat
summary['pass']=not any(summary[k] for k in ('schema_invalid','semantic_invalid','postprocess_changed_correct'))
print(json.dumps(summary,ensure_ascii=False,indent=2))
raise SystemExit(0 if summary['pass'] else 1)
