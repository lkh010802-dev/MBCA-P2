# LLM V1.3.1 16-FIELD LUNA HYBRID — RESILIENCE FREEZE

실서비스용 16-field intent parser의 **V1.3.1 최종 Freeze**입니다.

V1.3의 16-field 계약과 cost-optimized prompt를 유지하면서, Blind100 v2에서 발견된 3건을 deterministic postprocess로 보정했고, 여기에 timeout/retry/circuit breaker/result cache/fallback/logging으로 구성된 **Runtime Resilience Layer**를 추가했습니다.

> 공식 이력: V1.3 Blind100 v2 최초 unseen 점수는 **97/100**이며, 실패 3건을 보정한 뒤 동일 세트를 재처리한 V1.3.1 결과 **100/100**은 regression 결과로 구분해 기록합니다.

## 1. Production 구조

`사용자 입력 → Circuit check → GPT-5.6 Luna → Strict Structured Output(16 fields) → V1.3.1 deterministic postprocess → schema/semantic validation → 최종 intent`

장애 시:

`Luna 실패 → transient error만 최대 1회 retry → static exact-result cache → conservative deterministic fallback`

- model: `gpt-5.6-luna`
- reasoning: `none`
- prompt: V1.3과 동일
- schema: V1.3과 동일한 strict 16-field contract
- prompt cache: explicit 30m 유지
- normal LLM attempts: 1회
- SDK automatic retry: `max_retries=0`

## 2. V1.3.1 정확도 보정 — postprocess 3개

Blind100 v2 first run 97/100에서 발견된 3건을 프롬프트 증가 없이 deterministic postprocess로 보정했습니다.

1. generic `구경` 또는 landmark라는 이유만으로 `culture`를 과잉추론하지 않음
2. 명시적 `오전`을 `am`으로 literal normalization
3. `한두/두세 시간 뭐할까`를 availability가 아니라 desired-duration range로 보정

Prompt와 Schema는 변경하지 않았으므로 이 보정으로 인해 정상 LLM input prompt token이 추가되지 않습니다.

## 3. Runtime Resilience 기본 정책

- total deadline: **8초**
- first attempt timeout: **5초**
- max attempts: **2회** (= 최초 1회 + retry 최대 1회)
- retry delay: **0.35초**
- circuit breaker: **연속 API 실패 5회 → 30초 OPEN**
- result cache TTL: **24시간**
- result cache mode: **fallback-only**

Retry 대상은 timeout/connection, 408/409/429, 5xx, 드문 local output validation failure입니다. 잘못된 API key, 권한, bad request 등은 불필요하게 반복 호출하지 않습니다.

## 4. Result Cache 안전 규칙

이 Result Cache는 OpenAI Prompt Cache와 다른 **서비스 자체 최종 intent cache**입니다.

- 정상 요청에서 cache-first로 답하지 않음
- API failure 또는 circuit OPEN일 때만 조회
- parser version + model + normalized exact input으로 SHA-256 key 생성
- raw 사용자 문장 미저장
- 상대시간 의존 입력은 저장/재사용하지 않음
- cache DB 오류가 parser 전체 장애로 전파되지 않음

보수적으로 cache 제외되는 예:

- `지금`, `현재`, `오늘`, `내일`, `앞으로`, `지금부터`
- `2시간 뒤`, `30분 후` 등

## 5. Deterministic Fallback

API와 usable cache가 모두 없을 때만 사용합니다.

원칙은 **확실한 정보만 채우고 모르는 것은 null / [] / auto로 유지**하는 것입니다. 복잡한 location role을 로컬 규칙으로 억지 추론하지 않습니다.

고신뢰 cue 예:

- `카페/커피` → `cafe`
- `산책` → `walk` activity
- `걸어서/도보` → transport `walk`
- `지하철/버스` → `public_transit`
- 명시적 companion cue
- `오전/오후/아침/저녁` period
- 검증된 `한두 시간 뭐할까` 계열 duration range

## 6. Backend Contract

`parse_intent(..., include_debug=False)`는 기존 백엔드와 동일하게 **16개의 intent field만 반환**합니다.

내부 운영 로그가 필요하면 `include_debug=True`를 사용하고 `out["intent"]`만 기존 백엔드로 전달할 수 있습니다.

Debug metadata 주요 항목:

- `source`: `llm` / `result_cache` / `deterministic_fallback`
- `attempts`
- `latency_ms`
- `prompt_cache_hit`
- `result_cache_hit`
- `cache_eligible`
- `fallback_used`
- circuit state / failure count
- 마지막 error type/status

## 7. 검증 결과

### V1.3 역사적 기준

- Target Location Focus30: **30/30**
- Golden50: **50/50**
- Robustness30: **30/30**
- 위 회귀/포커스 합계: **110/110**
- Blind100 v2 first unseen run: **97/100**

### V1.3.1 보정 후

- Blind100 v2 reprocessed regression: **100/100**
- Golden50 API recheck: **50/50**
- Robustness30 API recheck: **30/30**
- known expected local fixed-point: **310/310**
- schema invalid: **0**
- semantic invalid: **0**
- postprocess changed correct expected: **0**

### Resilience

- zero-API fault injection: **25/25 PASS**
- real Luna API smoke: **5/5 PASS**
- smoke 5건 모두 `source=llm`, `attempts=1`
- smoke prompt cache: 첫 요청 cold, 이후 **4/4 hit**
- smoke latency: 3954 / 2555 / 1885 / 4345 / 2049 ms
- smoke total tokens: 2375 / 2376 / 2384 / 2387 / 2372

따라서 정상 환경에서 resilience layer가 불필요한 retry/fallback/cache 응답을 발생시키지 않는 것을 확인했습니다.

## 8. Windows SQLite Hotfix

Windows 테스트에서 임시 SQLite 파일 삭제 시 `WinError 32`가 발생한 이력이 있어, 모든 SQLite transaction 후 connection을 명시적으로 `close()`하도록 수정했습니다.

이 수정은 **resource cleanup만 변경**하며 prompt/schema/parser policy/retry/cache eligibility/fallback behavior에는 영향을 주지 않습니다.

## 9. 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`의 `OPENAI_API_KEY`만 실제 키로 변경합니다. `.env`는 Git에 올리지 않습니다.

## 10. Runtime 환경변수

```env
LLM_TOTAL_DEADLINE_SECONDS=8
LLM_FIRST_ATTEMPT_TIMEOUT_SECONDS=5
LLM_RETRY_DELAY_SECONDS=0.35
LLM_MAX_ATTEMPTS=2
LLM_CIRCUIT_FAILURE_THRESHOLD=5
LLM_CIRCUIT_OPEN_SECONDS=30
LLM_RESULT_CACHE_ENABLED=true
LLM_RESULT_CACHE_TTL_SECONDS=86400
LLM_RESULT_CACHE_PATH=.runtime_cache/intent_result_cache.sqlite3
LLM_RUNTIME_LOG_PATH=
```

초기 배포에서는 기본값 그대로 사용하는 것을 권장합니다.

## 11. 무료 검증 명령

```powershell
python test_blind100_v2_fail3_local.py
python validate_v1_3_1_freeze.py
python test_runtime_resilience.py
```

기대 결과:

- Blind failure boundary: 7/7 PASS
- known expected: 310/310 PASS
- resilience: 25/25 PASS

## 12. 실제 API smoke

필요 시에만:

```powershell
python smoke_resilience_api.py
```

정상 환경에서는 `source=llm attempts=1`이 기본입니다.

## 13. 핵심 파일

- `intent_parser.py` — production entry point + OpenAI wiring
- `runtime_resilience.py` — deadline/retry/circuit/result-cache/fallback/logging
- `intent_postprocess.py` — V1.3.1 deterministic corrections
- `intent_parser_prompt_team_v1_3_COST_OPT.txt` — V1.3 prompt, unchanged
- `user_intent_schema_team_v1_3_STRICT.json` — 16-field strict schema, unchanged
- `test_runtime_resilience.py` — 25-case zero-API fault injection
- `smoke_resilience_api.py` — 5-case real API smoke
- `docs/V1.3.1_변경사항_및_운영안정성_설명서.docx` — 변경점/운영 설명 문서

## 14. Freeze 원칙

이 폴더는 **V1.3.1 Freeze**로 취급합니다. 이후 정책/프롬프트/schema/postprocess/resilience behavior를 변경할 경우 이 폴더를 덮어쓰지 않고 다음 Candidate/Freeze 버전을 새 폴더로 생성합니다.

> 참고: `DEFAULT_PROMPT_CACHE_KEY` 문자열에는 과거 candidate 명칭이 남아 있으나, 실제 prompt cache locality를 유지하기 위해 Freeze 시점에 의도적으로 변경하지 않았습니다. 기능/버전 판정용 key는 Result Cache의 `PARSER_VERSION=1.3.1`과 별도로 관리됩니다.
