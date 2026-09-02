#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local-only microbenchmark. No OpenAI API calls or tokens."""
import copy
import statistics
import tempfile
import time
from pathlib import Path
from runtime_resilience import CircuitBreaker, INTENT_DEFAULTS, ResultCache, deterministic_fallback


def measure(fn, n=300):
    xs=[]
    for _ in range(n):
        t=time.perf_counter(); fn(); xs.append((time.perf_counter()-t)*1000)
    xs.sort()
    return {"n":n,"median_ms":round(statistics.median(xs),4),"p95_ms":round(xs[int(n*0.95)-1],4),"max_ms":round(max(xs),4)}

with tempfile.TemporaryDirectory() as td:
    cb=CircuitBreaker(5,30)
    cache=ResultCache(str(Path(td)/'cache.sqlite3'),86400)
    intent=copy.deepcopy(INTENT_DEFAULTS); intent['activities']=['cafe']
    key='k'*64
    cache.put(key,intent)
    print('circuit_closed_check', measure(lambda: cb.allow_request(),1000))
    print('sqlite_cache_get', measure(lambda: cache.get(key),300))
    print('sqlite_cache_put', measure(lambda: cache.put(key,intent),300))
    print('deterministic_fallback', measure(lambda: deterministic_fallback('오전에 친구랑 카페 가고 싶어',{}),300))
