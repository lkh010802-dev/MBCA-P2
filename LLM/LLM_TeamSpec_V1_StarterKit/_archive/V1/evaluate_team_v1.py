#!/usr/bin/env python3
import argparse, csv, json
from pathlib import Path
from collections import Counter
try:
    from jsonschema import Draft202012Validator
except ImportError:
    raise SystemExit('jsonschema 필요: pip install -U jsonschema')
HERE=Path(__file__).resolve().parent

def load_jsonl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()]

def f1_sets(a,b):
    a,b=set(a),set(b)
    if not a and not b: return 1.0
    if not a or not b: return 0.0
    tp=len(a&b); p=tp/len(b); r=tp/len(a)
    return 0.0 if p+r==0 else 2*p*r/(p+r)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('predictions')
    ap.add_argument('--golden',default=str(HERE/'golden_tests_50_team_v1.jsonl'))
    ap.add_argument('--schema',default=str(HERE/'user_intent_schema_team_v1.json'))
    ap.add_argument('--out-dir',default='evaluation_result_team_v1')
    args=ap.parse_args()
    gold={x['test_id']:x for x in load_jsonl(args.golden)}
    pred_rows=load_jsonl(args.predictions)
    preds={x['test_id']:x for x in pred_rows}
    schema=json.loads(Path(args.schema).read_text(encoding='utf-8'))
    validator=Draft202012Validator(schema)
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)

    fields=['start_location_text','end_location_text','start_time','end_time','desired_duration_minutes','transport_mode','budget_max','budget_preference','space_preference']
    field_hits=Counter(); field_total=Counter()
    schema_valid=0; activity_f1=[]; companion_f1=[]; exact_cases=0
    failures=[]; rows=[]
    default_hallucinations=0; default_opportunities=0

    for tid in sorted(gold):
        g=gold[tid]; prow=preds.get(tid,{})
        p=prow.get('predicted')
        errs=[]
        if not isinstance(p,dict):
            errs.append('MISSING_PREDICTION')
            p={}
        schema_errs=list(validator.iter_errors(p)) if p else []
        if schema_errs:
            errs.append('SCHEMA_INVALID')
        else:
            schema_valid+=1
        exp=g['expected']
        for f in fields:
            field_total[f]+=1
            if p.get(f)==exp.get(f): field_hits[f]+=1
        af1=f1_sets(exp.get('activities',[]),p.get('activities',[])); activity_f1.append(af1)
        cf1=f1_sets(exp.get('companions',[]),p.get('companions',[])); companion_f1.append(cf1)
        if af1<1: errs.append('ACTIVITY_MISMATCH')
        if cf1<1: errs.append('COMPANION_MISMATCH')
        for f in fields:
            if p.get(f)!=exp.get(f): errs.append(f'{f.upper()}_MISMATCH')
        # default hallucination: expected default/null but model invents value
        defaults={'start_location_text':None,'end_location_text':None,'start_time':None,'end_time':None,'desired_duration_minutes':None,'transport_mode':'auto','budget_max':None,'budget_preference':None,'space_preference':None}
        for f,d in defaults.items():
            if exp.get(f)==d:
                default_opportunities+=1
                if p.get(f)!=d: default_hallucinations+=1
        if exp.get('activities',[])==[]:
            default_opportunities+=1
            if p.get('activities',[])!=[]: default_hallucinations+=1
        if exp.get('companions',[])==[]:
            default_opportunities+=1
            if p.get('companions',[])!=[]: default_hallucinations+=1
        if not errs: exact_cases+=1
        if errs: failures.extend(errs)
        rows.append({
          'test_id':tid,'input':g['input'],'schema_valid':not schema_errs,
          'errors':'|'.join(dict.fromkeys(errs)) or 'PASS',
          'activity_f1':round(af1,3),'companion_f1':round(cf1,3),
          'expected_json':json.dumps(exp,ensure_ascii=False),
          'predicted_json':json.dumps(p,ensure_ascii=False)
        })

    n=len(gold)
    summary={
      'cases_expected':n,
      'cases_received':len(preds),
      'schema_validity':schema_valid/n,
      'exact_case_accuracy':exact_cases/n,
      'activity_f1':sum(activity_f1)/n,
      'companions_f1':sum(companion_f1)/n,
      'default_hallucination_rate': (default_hallucinations/default_opportunities if default_opportunities else 0),
      'field_accuracy':{f:field_hits[f]/field_total[f] for f in fields},
      'failure_type_counts':dict(Counter(failures)),
      'recommended_gates':{
        'schema_validity':'>= 1.00',
        'exact_case_accuracy':'>= 0.90',
        'activity_f1':'>= 0.95',
        'companions_f1':'>= 0.95',
        'default_hallucination_rate':'< 0.02'
      }
    }
    (out/'evaluation_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'evaluation_cases.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    html=['<!doctype html><meta charset="utf-8"><title>Team Spec V1 Eval</title>',
          '<style>body{font-family:Arial,Malgun Gothic,sans-serif;max-width:1100px;margin:30px auto}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:7px}th{background:#17365D;color:white}</style>',
          '<h1>Team Spec V1 Evaluation</h1><h2>Summary</h2><pre>'+json.dumps(summary,ensure_ascii=False,indent=2)+'</pre>',
          '<h2>Cases</h2><table><tr><th>ID</th><th>Input</th><th>Errors</th><th>Activity F1</th><th>Companion F1</th></tr>']
    for r in rows:
        html.append(f"<tr><td>{r['test_id']}</td><td>{r['input']}</td><td>{r['errors']}</td><td>{r['activity_f1']}</td><td>{r['companion_f1']}</td></tr>")
    html.append('</table>')
    (out/'evaluation_report.html').write_text(''.join(html),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
