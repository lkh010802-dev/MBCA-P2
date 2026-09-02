#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small paid integration smoke test for the resilience-wrapped production parser."""
import json
from intent_parser import parse_intent

CTX={"current_datetime":"2026-09-02T17:00:00+09:00","timezone":"Asia/Seoul"}
CASES=[
    "홍대에서 카페 가고 싶어",
    "오전에 북촌에서 산책하고 싶어",
    "7시에 홍대에서 친구 만나야 해. 그 전에 카페 갈래",
    "경복궁에서 구경하고 저녁쯤 광화문 가야 해",
    "지금부터 한두 시간 뭐할까?",
]

for i,text in enumerate(CASES,1):
    out=parse_intent(text,CTX,include_debug=True)
    r=out["runtime"]
    print(f"[{i}/{len(CASES)}] source={r['source']} attempts={r['attempts']} latency_ms={r['latency_ms']} cached_prompt={r['prompt_cache_hit']} tokens={out['usage']['total_tokens']}")
    print(json.dumps(out["intent"],ensure_ascii=False))
