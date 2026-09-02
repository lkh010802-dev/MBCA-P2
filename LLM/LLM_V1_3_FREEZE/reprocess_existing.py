#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, json
from pathlib import Path
from intent_postprocess import postprocess_intent

def load_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--overwrite',action='store_true')
    args=ap.parse_args()
    src,dst=Path(args.input),Path(args.output)
    if dst.exists() and not args.overwrite:
        raise SystemExit(f'Output exists: {dst} (use --overwrite)')
    dst.parent.mkdir(parents=True,exist_ok=True)
    rows=load_jsonl(src); changed_cases=changed_fields=0
    with dst.open('w',encoding='utf-8') as f:
        for row in rows:
            base=row.get('llm_predicted') if isinstance(row.get('llm_predicted'),dict) else row.get('predicted')
            pred,changes=postprocess_intent(row.get('input',''),row.get('runtime_context') or {},base) if isinstance(base,dict) else (base,[])
            out=dict(row); out['predicted']=pred; out['postprocess_changes']=changes; out['reprocessed_without_api']=True
            f.write(json.dumps(out,ensure_ascii=False)+'\n')
            if changes:
                changed_cases += 1; changed_fields += len(changes)
                print(f"#{row.get('test_id')} changed: "+', '.join(c.get('field','?') for c in changes))
    print(json.dumps({'cases':len(rows),'changed_cases':changed_cases,'changed_fields':changed_fields,
                      'api_calls':0,'new_tokens':0,'output':str(dst)},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
