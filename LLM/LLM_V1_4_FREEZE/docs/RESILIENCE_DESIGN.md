# Runtime Resilience Design — V1.3.1 Freeze

## Goals

1. 정상 요청의 LLM 호출 횟수와 prompt token을 늘리지 않는다.
2. timeout/network/429/5xx에서 무한 대기하지 않는다.
3. SDK default retry와 application retry가 중첩되지 않게 한다.
4. 장기 장애 시 circuit breaker로 추가 API 호출을 억제한다.
5. Result Cache는 exact + parser/model isolated + time-independent 조건에서만 fallback으로 사용한다.
6. Cache가 없으면 conservative deterministic fallback으로 16-field schema를 유지한다.

## Retry policy

OpenAI client는 `max_retries=0`으로 생성합니다.

Application retry 대상:

- timeout / connection error
- 408 / 409 / 429
- 5xx
- 매우 드문 local output validation failure

Bad request/auth/permission 등은 재시도하지 않고 cache/fallback으로 이동합니다.

## Deadline

기본 전체 deadline 8초.

- 1차 시도 최대 5초
- transient failure가 빠르게 발생하면 0.35초 후 2차 시도
- 2차 timeout은 남은 전체 deadline만큼만 허용
- 최대 attempts=2

## Circuit breaker

기본 연속 API failure 5회에서 OPEN, 30초 유지합니다.

OPEN 동안 API는 호출하지 않고 cache/fallback으로 즉시 이동합니다. 시간이 지나면 한 요청만 HALF_OPEN probe로 허용하며 성공 시 CLOSED, 실패 시 다시 OPEN됩니다.

현재 circuit state는 **process-local**입니다. 여러 worker에서는 worker별로 독립 circuit이 작동합니다. Result Cache SQLite는 동일 path를 쓰는 worker 사이에 공유 가능합니다.

## Result Cache

SQLite WAL 기반 exact final-intent cache입니다.

- normal path에서는 read하지 않음
- successful static input은 cache에 저장
- API failure/circuit OPEN 때만 read
- raw user input 미저장
- SHA-256 key: parser version + model + normalized exact input
- TTL default 86400s
- DB lock/cache failure는 사용자 요청 실패로 전파하지 않음
- Windows file locking 문제 방지를 위해 transaction 후 connection을 명시적으로 close

## Relative-time exclusion

보수적으로 `지금/현재/오늘/내일/앞으로/지금부터/N시간 뒤/N분 후` 등이 있으면 cache eligible=false입니다.

## Deterministic fallback

완전한 parser가 아닙니다. 확실한 activity/transport/companion/period/space cue와 이미 검증된 V1.3.1 postprocess만 사용합니다. 복잡한 location role은 억지로 추론하지 않습니다.

## Observability

`include_debug=True`에서 runtime metadata를 반환합니다.

- source
- attempts
- latency_ms
- prompt_cache_hit
- result_cache_hit
- cache_eligible
- fallback_used
- circuit state/failure count
- 마지막 error type/status

`LLM_RUNTIME_LOG_PATH`를 지정하면 runtime metadata만 JSONL로 기록합니다. 기본은 비활성화입니다.
