#!/usr/bin/env python3
import argparse,json,os,time
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    raise SystemExit('python-dotenv 필요: pip install -U python-dotenv')
try:
    from openai import OpenAI
except ImportError:
    raise SystemExit('openai 필요: pip install -U openai')
HERE=Path(__file__).resolve().parent
load_dotenv(HERE/'.env')

def load_jsonl(p): return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()]
def append(p,row):
    with Path(p).open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--model',default='gpt-5.6-terra')
    ap.add_argument('--input',default=str(HERE/'eval_inputs_50_team_v1.jsonl'))
    ap.add_argument('--prompt',default=str(HERE/'intent_parser_prompt_team_v1.txt'))
    ap.add_argument('--schema',default=str(HERE/'user_intent_schema_team_v1.json'))
    ap.add_argument('--output',default=str(HERE/'predictions_team_v1.jsonl'))
    ap.add_argument('--limit',type=int,default=None)
    ap.add_argument('--overwrite',action='store_true')
    args=ap.parse_args()
    if not os.getenv('OPENAI_API_KEY'): raise SystemExit('.env에 OPENAI_API_KEY가 필요합니다.')
    rows=load_jsonl(args.input)
    if args.limit: rows=rows[:args.limit]
    op=Path(args.output)
    if args.overwrite and op.exists(): op.unlink()
    prompt=Path(args.prompt).read_text(encoding='utf-8')
    schema=Path(args.schema).read_text(encoding='utf-8')
    instructions=prompt+'\n\n# 실제 평가 JSON Schema\n'+schema
    client=OpenAI()
    for idx,row in enumerate(rows,1):
        print(f"[{idx}/{len(rows)}] #{row['test_id']} {row['input']}")
        predicted=None; raw=''; err=None
        try:
            resp=client.responses.create(
              model=args.model,
              instructions=instructions,
              input='Return exactly one valid JSON object only. Follow the supplied JSON Schema exactly.\n\nUser request:\n'+row['input'],
              text={'format':{'type':'json_object'}}
            )
            raw=resp.output_text.strip(); obj=json.loads(raw)
            predicted=obj if isinstance(obj,dict) else None
            if predicted is None: err='JSON root is not an object'
        except Exception as e: err=f'{type(e).__name__}: {e}'
        append(op,{'test_id':row['test_id'],'input':row['input'],'predicted':predicted,'raw_output':raw,'api_error':err})
        print('  -> OK' if not err else '  -> ERROR '+err)
        time.sleep(.2)
    print('\nEvaluation:')
    print(f'python evaluate_team_v1.py {op.name} --out-dir evaluation_result_team_v1')
if __name__=='__main__': main()
