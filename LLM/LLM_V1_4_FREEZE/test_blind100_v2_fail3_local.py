#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from intent_postprocess import postprocess_intent

CTX={"current_datetime":"2026-09-01T17:00:00+09:00","timezone":"Asia/Seoul"}
BASE={
  "start_location_text":None,"target_location_text":None,"target_location_scope":None,"end_location_text":None,
  "start_time":None,"end_time":None,"start_time_period":None,"end_time_period":None,
  "desired_duration_min_minutes":None,"desired_duration_max_minutes":None,"activities":[],
  "transport_mode":"auto","companions":[],"budget_max":None,"budget_preference":None,"space_preference":None,
}

def obj(**kw):
    x=dict(BASE); x.update(kw); return x

CASES=[
  {
    "id":10,"input":"경복궁에서 구경하고 저녁쯤 광화문 가야 해",
    "predicted":obj(target_location_text="경복궁",target_location_scope="place",end_location_text="광화문",end_time_period="evening",activities=["culture"]),
    "expected":obj(target_location_text="경복궁",target_location_scope="place",end_location_text="광화문",end_time_period="evening",activities=[]),
  },
  {
    "id":19,"input":"오전에 북촌에서 산책하고 싶어",
    "predicted":obj(target_location_text="북촌",target_location_scope="area",start_time_period="morning",activities=["walk"]),
    "expected":obj(target_location_text="북촌",target_location_scope="area",start_time_period="am",activities=["walk"]),
  },
  {
    "id":55,"input":"지금부터 한두 시간 뭐할까?",
    "predicted":obj(end_time="19:00"),
    "expected":obj(desired_duration_min_minutes=60,desired_duration_max_minutes=120),
  },
  # boundaries: explicit culture must stay, and availability must not become desired duration.
  {
    "id":"b1","input":"경복궁에서 전시 보고 싶어",
    "predicted":obj(target_location_text="경복궁",target_location_scope="place",activities=["culture"]),
    "expected":obj(target_location_text="경복궁",target_location_scope="place",activities=["culture"]),
  },
  {
    "id":"b2","input":"오전에 전시 보고 싶어",
    "predicted":obj(start_time_period="am",activities=["culture"]),
    "expected":obj(start_time_period="am",activities=["culture"]),
  },
  {
    "id":"b3","input":"한두 시간 시간 있어",
    "predicted":obj(),
    "expected":obj(end_time="19:00"), # compact desired-range rule must NOT fire; availability still wins.
  },
  {
    "id":"b4","input":"두세 시간 뭐할까?",
    "predicted":obj(end_time="20:00"),
    "expected":obj(desired_duration_min_minutes=120,desired_duration_max_minutes=180),
  },
]

failed=[]
for c in CASES:
    out,changes=postprocess_intent(c["input"],CTX,c["predicted"])
    ok=(out==c["expected"])
    print(f"[{c['id']}] {'PASS' if ok else 'FAIL'} {c['input']}")
    if not ok:
        failed.append({"id":c["id"],"input":c["input"],"expected":c["expected"],"actual":out,"changes":changes})
print(json.dumps({"cases":len(CASES),"passed":len(CASES)-len(failed),"failed":len(failed)},ensure_ascii=False,indent=2))
if failed:
    print(json.dumps(failed,ensure_ascii=False,indent=2))
    raise SystemExit(1)
