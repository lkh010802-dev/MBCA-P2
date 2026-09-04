# Changelog

## 1.0.1 backend-adapter / Git clean refresh - 2026-09-04

- duplicate REVIEW 14건을 명시적 review decision으로 해소하여 최신 일일 실행에서 duplicate_review=0 / master commit 성공 상태를 반영했습니다.
- DayForYou 운영시간 parser hotfix5를 누적하여 공백형 시간 범위, Open 표기, 휴무일 예외 및 공연 회차 오인 방지를 반영했습니다.
- 일일 CSV의 `today_opening_time` / `today_closing_time`을 백엔드 `opening_time` / `closing_time`으로 변환하는 `backend_adapter`를 추가했습니다.
- Popup source를 Kakao/Tour와 같은 공통 place dict 핵심 필드로 변환하며, 원래 팝업 분류는 `category_detail`에 보존합니다.
- `run_daily.py` 성공 후 `backend_output/YYYYMMDD_popup_places.json`과 `latest_popup_places.json`을 자동 생성합니다.
- 정적 JSON의 `distance_m`은 null로 두고, backend runtime loader에 기준 좌표를 넘기면 haversine 거리와 radius filtering을 계산할 수 있습니다.
- Git 배포본에서 `.venv`, runtime data/output/log, cache/pyc, 빌드된 EXE를 제외했습니다.
- regression suite: 146 tests passed.

## 1.0.1 operation-hours/backend-readiness - 2026-09-04

- DayForYou 운영시간 누락 원인 수정: 기존에는 LLM 검토 후보만 상세페이지를 수집했으나, 이제 서울 후보 전체 상세페이지를 재파싱해 운영시간을 보강합니다.
- DayForYou `.schedule_detail`의 `⏰ 시간 : 10:30~22:00`, `평일 ...`, `월-목 ... / 금-일 ...` 등 운영시간 형식을 원문 그대로 추출합니다.
- `operation_hours_raw`, `operation_schedule`, `opening_time`, `closing_time` 백엔드 컬럼을 추가했습니다.
- 요일별 시간/휴무/공휴일을 deterministic parser로 구조화하고, 모든 요일에 단일 시간이 동일할 때만 opening/closing을 생성합니다.
- `operation_hours_missing_details.jsonl` 및 daily 운영시간 coverage 지표를 추가했습니다.
- 동일 DayForYou upstream event가 서로 다른 scheduleSeq로 중복 등록된 경우, 공식 URL+주소+기간+이름이 모두 강하게 일치할 때만 same-source exact duplicate로 자동 병합합니다.
- 좌표 보완 hotfix2 기능은 그대로 유지합니다.
- regression suite: 114 tests passed.

## 1.0.0 coordinate enrichment hotfix 2 - 2026-09-03

- Fixed numbered-gil spacing such as `백제고분로 41길 24` being truncated to `백제고분로 41`.
- Re-derive `address_base` from the full address so old/bad source-normalized values are repaired during both daily integration and CSV backfill.
- Added free-form district inference for location strings such as `서울 용산 아이파크몰 ...`.
- Added concise Kakao keyword hints for mall/venue text and hashtag-style location strings.
- Added road-address keyword fallback after Kakao address search misses.
- Added unresolved diagnostic fields (`geocode_address_query`, `geocode_keyword_queries`, `geocode_unresolved_reason`) without changing the backend 31-column CSV contract.
- Added regression tests for all three unresolved 2026-09-02/03 patterns.

## 1.0.0 coordinate enrichment patch - 2026-09-03

- Added post-canonical missing latitude/longitude enrichment without overwriting valid source coordinates.
- Added persistent Kakao geocode cache and conservative same-address coordinate reuse.
- Added Kakao address search with venue/address/name keyword fallback.
- Added `geocode_report.json` and `geocode_unresolved.jsonl` audit artifacts.
- Added optional `KAKAO_REST_API_KEY` configuration and `--no-geocode` escape hatch.

## 1.0.0 - 2026-09-01

- First internal operations/backend handoff release.
- Freeze v0.9.7 classification/duplicate review resolution baseline.
- Added Windows daily scheduler setup/remove/status scripts.
- Added unattended scheduled runner and scheduler logs.
- Standardized top-level version labels to 1.0.0.
- Added backend handoff, CSV schema, install/schedule, and operations runbook docs.
- Runtime data/output/logs excluded from source-control defaults.
