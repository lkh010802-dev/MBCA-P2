#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from intent_postprocess import postprocess_intent


def load_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]


def semantic_errors(obj):
    errors=[]
    if obj.get('start_time') is not None and obj.get('start_time_period') is not None:
        errors.append('START_TIME_PERIOD_CONFLICT')
    if obj.get('end_time') is not None and obj.get('end_time_period') is not None:
        errors.append('END_TIME_PERIOD_CONFLICT')
    target=obj.get('target_location_text'); scope=obj.get('target_location_scope')
    if target is None and scope is not None: errors.append('TARGET_SCOPE_WITHOUT_LOCATION')
    if target is not None and scope is None: errors.append('TARGET_LOCATION_WITHOUT_SCOPE')
    dmin=obj.get('desired_duration_min_minutes'); dmax=obj.get('desired_duration_max_minutes')
    if dmin is not None and dmax is not None and dmin>dmax: errors.append('DURATION_RANGE_INVALID')
    for field in ('activities','companions'):
        vals=obj.get(field,[])
        if isinstance(vals,list) and len(vals)!=len(set(vals)): errors.append(field.upper()+'_DUPLICATE')
    return errors


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    blind_inputs=load_jsonl(HERE/'tests/blind100_v2/inputs.jsonl')
    blind_golden=load_jsonl(HERE/'tests/blind100_v2/golden.jsonl')
    schema=json.loads((HERE/'user_intent_schema_team_v1_3_STRICT.json').read_text(encoding='utf-8'))
    validator=Draft202012Validator(schema)

    prior_paths=[
        HERE/'tests/regression/golden50/inputs.jsonl',
        HERE/'tests/regression/robustness30/inputs.jsonl',
        HERE/'tests/expansion/blind100_migrated/inputs.jsonl',
        HERE/'tests/focus/target_location30/inputs.jsonl',
    ]
    prior=[]
    for p in prior_paths: prior.extend(load_jsonl(p))
    prior_text={x['input'] for x in prior}
    overlap=[x['test_id'] for x in blind_inputs if x['input'] in prior_text]
    dup_count=len(blind_inputs)-len({x['input'] for x in blind_inputs})

    schema_invalid=[]; semantic_invalid=[]; post_changed=[]
    for row in blind_golden:
        expected=row['expected']
        errs=list(validator.iter_errors(expected))
        if errs: schema_invalid.append(row['test_id'])
        sem=semantic_errors(expected)
        if sem: semantic_invalid.append({'test_id':row['test_id'],'errors':sem})
        out,changes=postprocess_intent(row['input'],row.get('runtime_context') or {},expected)
        if out != expected:
            post_changed.append({'test_id':row['test_id'],'changes':changes})

    manifest=json.loads((HERE/'FREEZE_MANIFEST.json').read_text(encoding='utf-8'))
    hash_mismatch=[]
    for rel,expected_hash in manifest['freeze_core_sha256'].items():
        actual=sha256(HERE/rel)
        if actual!=expected_hash: hash_mismatch.append({'file':rel,'expected':expected_hash,'actual':actual})

    result={
        'blind_cases':len(blind_inputs),
        'golden_cases':len(blind_golden),
        'prior_cases_checked':len(prior),
        'exact_overlap_with_prior':len(overlap),
        'duplicate_inputs_inside_blind':dup_count,
        'schema_invalid':len(schema_invalid),
        'semantic_invalid':len(semantic_invalid),
        'postprocess_changed_correct':len(post_changed),
        'freeze_core_hashes_ok':not hash_mismatch,
        'pass':(
            len(blind_inputs)==100 and len(blind_golden)==100 and not overlap and dup_count==0
            and not schema_invalid and not semantic_invalid and not post_changed and not hash_mismatch
        )
    }
    if overlap: result['overlap_test_ids']=overlap
    if schema_invalid: result['schema_invalid_test_ids']=schema_invalid
    if semantic_invalid: result['semantic_invalid_details']=semantic_invalid
    if post_changed: result['postprocess_changed_details']=post_changed
    if hash_mismatch: result['hash_mismatch']=hash_mismatch
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['pass']: raise SystemExit(1)

if __name__=='__main__': main()
