# Validation Results — V1.3.1 Resilience Freeze

## Historical V1.3 baseline

- Target Location Focus30: 30/30
- Golden50: 50/50
- Robustness30: 30/30
- Regression/focus total: 110/110
- Blind100 v2 first unseen run: **97/100**

The 97/100 score is preserved as the true first-run blind generalization score.

## V1.3.1 correction rechecks

- Blind100 v2 reprocessed regression: 100/100
- Golden50 API recheck: 50/50
- Robustness30 API recheck: 30/30

## Local known-set validation

`python validate_v1_3_1_freeze.py`

- total known expected: 310
- schema_invalid: 0
- semantic_invalid: 0
- postprocess_changed_correct: 0
- PASS

## Resilience fault injection

`python test_runtime_resilience.py`

- cases: 25
- passed: 25
- failed: 0
- PASS

The suite uses no API tokens and covers normal success, one controlled retry, non-retryable failure, repeated transient failure, static exact-result cache failover, relative-time cache exclusion, circuit open/half-open, TTL, parser/model cache isolation, conservative fallback, and Windows SQLite cleanup.

## Real API smoke

`python smoke_resilience_api.py`

User-run final smoke results:

| Case | source | attempts | latency_ms | prompt_cache | total_tokens |
|---|---|---:|---:|---|---:|
| 1 | llm | 1 | 3954 | cold | 2375 |
| 2 | llm | 1 | 2555 | hit | 2376 |
| 3 | llm | 1 | 1885 | hit | 2384 |
| 4 | llm | 1 | 4345 | hit | 2387 |
| 5 | llm | 1 | 2049 | hit | 2372 |

Summary:

- 5/5 successful
- all `source=llm`
- all `attempts=1`
- no unnecessary retry/fallback/result-cache response
- prompt cache warm hits: 4/4 after first cold request
- average latency: ~2.96 s
- average total tokens: ~2378.8

## Local microbenchmark (indicative only)

Package-build container observations:

- circuit closed check median: ~0.0004 ms
- SQLite cache get median: ~0.64 ms
- SQLite cache put median: ~1.82 ms
- deterministic fallback median: ~0.05 ms

These are not production guarantees. Re-run `benchmark_resilience_local.py` on the deployment host when needed.
