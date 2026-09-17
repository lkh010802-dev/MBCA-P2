# KOALA Backend — MVP v2

KOALA는 사용자의 자연어 요청, 현재 위치, 가용 시간과 이동수단을 바탕으로 서울의 지역과 실제 장소를 추천하고, 선택한 장소를 실제 이동시간 기준으로 최적화해 방문 코스를 만드는 FastAPI 백엔드입니다.

LLM은 자연어를 구조화된 조건으로 변환하는 역할을 담당합니다. 지역·장소·코스의 실제 추천 판단은 백엔드가 시간, 거리, 실제 이동시간, 활동 적합도, 혼잡도, 운영시간을 계산해 결정합니다.

## 추천 흐름

```text
사용자 자연어 + GPS
        ↓
LLM 의도 구조화
        ↓
시작·목적·종료 위치와 시간창 해석
        ↓
종료 임박 팝업·문화행사 선제 추천
        ↓
서울 121개 지역 후보 평가
  · 거리와 실제 이동시간
  · 활동 적합도
  · 예상 도착시간의 혼잡도
        ↓
선택 지역 주변 실제 장소 추천
  · Kakao Local / TourAPI
  · 서울 문화행사 / Popup
  · 거리 및 실내·야외 선호 soft scoring
  · 활동별 round-robin
        ↓
장소 선택 사전검증
        ↓
선택 장소 전체의 방문 순서 최적화
        ↓
구간별 실제 이동시간 + 체류시간 계산
        ↓
예상 도착시간 기준 장소 availability 계산
        ↓
FEASIBLE / INFEASIBLE 코스 반환
```

## 주요 기능

### 자연어 의도 구조화

- 시작 위치, 목적 지역·장소, 종료 위치
- 시작·종료 시간과 희망 체류시간 범위
- `food`, `cafe`, `walk`, `culture`, `entertainment`, `shopping`, `drink`
- `auto`, `public_transit`, `walk`, `car`
- 동행 유형과 실내·야외 선호
- LLM V1.4 Freeze의 resilience, retry, circuit breaker 및 결과 캐시

LLM이 만든 조건은 `StructuredConditions`로 검증됩니다. 추천 결과 설명은 두 번째 LLM 호출 없이 백엔드의 deterministic template으로 생성합니다.

### 종료 임박 선제 추천

지역 추천과 함께 현재 위치에서 실제로 방문 가능한 팝업 또는 서울 문화행사를 최대 1개 제안합니다.

- 출발일 기준 오늘부터 3일 안에 종료되는 행사
- 현재 위치에서 직선거리 2km 이내 후보
- 상위 3개 후보만 실제 이동시간 확인
- 운영 중이며 활동별 최소 체류시간을 확보할 수 있는 후보
- 사용자 시간창과 다음 일정이 있으면 이동시간과 10분 안전 버퍼 반영
- `timely`: 요청 활동과 일치하거나 활동을 지정하지 않은 종료 임박 추천
- `detour`: 요청 활동과 다르지만 오늘 종료되고 실제 이동시간이 15분 이내인 제안

Popup과 서울 문화행사 중 한 소스가 실패해도 다른 추천과 기존 지역 추천은 계속 진행합니다.

### 서울 지역 추천

서울 주요 121개 POI를 대상으로 다음 정보를 계산합니다.

- 현재 위치 또는 지정한 목적 지역과의 거리
- 종료 위치가 있을 때의 우회 동선
- 실제 이동시간과 사용자 시간창
- 상권 CSV 기반 활동 적합도
- 예상 도착시간에 가장 가까운 서울 혼잡도 예측
- 활동, 이동, 혼잡도 점수를 합산한 최종 순위
- 일반 추천과 이동 부담이 큰 `extended` 후보 분리

`recommendation_context`에는 다음 단계에서 재사용할 구조화 값이 포함됩니다.

- `activities`, `transport_mode`, `space_preference`
- 해석된 `start_location`, `end_location`
- timezone-aware `departure_datetime`, `end_datetime`
- `available_time_minutes`

### 실제 장소 추천

선택한 지역 중심 2km 안에서 여러 데이터 소스의 후보를 수집합니다. 중복 제거 후 거리 점수와 실내·야외 선호 가점을 계산하고, 여러 활동이 요청되면 활동별 round-robin으로 결과를 구성합니다.

- 한 페이지에 6개 장소 반환
- 다음 후보는 15분 TTL의 process-memory cursor cache에서 반환
- `/recommend/places/more`는 외부 장소 API를 다시 호출하지 않음
- 만료된 cursor는 `410`, 존재하지 않는 cursor는 `404`

장소에는 가능한 범위에서 다음 공간 metadata가 붙습니다.

- `space_type`: `indoor`, `outdoor`, `mixed`, `unknown`
- `space_type_confidence`: `high`, `medium`, `unknown`
- `space_type_basis`: `explicit`, `category`, `venue`, `unknown`

`space_preference`는 hard filter가 아니라 보수적인 soft scoring으로만 사용합니다. 근거가 부족한 `unknown` 장소는 불이익을 받지 않습니다.

### 장소 선택 사전검증

- 코스당 1~6개 장소
- 활동별 최소·기본 체류시간
- 사용자가 지정한 장소별 체류시간 반영
- 선택 단계의 거리 기반 예상 이동시간과 예상 방문 순서
- 총 가용시간 대비 체류시간 검증

이 단계의 이동시간은 빠른 피드백을 위한 휴리스틱입니다. `travel_time_precheck.warning`은 경고이며 최종 hard rejection이 아닙니다.

### 코스 최적화와 availability

- 선택한 모든 장소를 포함하는 exhaustive permutation
- 시작 위치 고정, 종료 위치가 있으면 종료 위치 고정
- `preferred_first=true` 장소가 하나 있으면 첫 방문지로 고정
- directed leg 단위의 실제 이동시간 및 request-level cache
- 실패한 이동 구간도 요청 범위에서 캐시
- 한 순서의 이동 구간이 실패하면 해당 완전한 순서만 제외
- 계산 가능한 순서 중 실제 총 이동시간이 가장 짧은 순서 선택
- 체류시간과 이동시간을 합산해 `FEASIBLE` 또는 `INFEASIBLE` 판정

`departure_datetime`이 전달되면 각 장소의 예상 도착시간을 순서대로 누적하고 `operation_schedule`을 이용해 장소별 availability를 계산합니다. availability가 `closed`여도 이번 MVP에서는 장소 제거, 재정렬 또는 코스 상태 변경에 사용하지 않습니다.

availability 상태:

- `open`
- `closed`
- `not_yet_open`
- `unknown`
- `event_not_started`
- `event_ended`

운영시간이 없거나 확실히 파싱되지 않은 장소는 일반 추천에서 제외하지 않고 `unknown`으로 처리합니다. 자정 이후 마감, 24시간 운영, 하루의 여러 운영 구간과 휴무 일정도 공통 계산에서 처리합니다.

### 회원 및 인증

- MySQL + SQLAlchemy
- 이메일 정규화 및 중복 방지 회원가입
- Argon2 비밀번호 해싱
- JWT HS256 Access Token 발급
- Bearer Token 기반 현재 사용자 조회
- 요청 단위 DB Session 및 종료 시 close

추천 API는 현재 MVP 정책상 로그인 없이 사용할 수 있습니다. DB에는 `users`, `user_preferences`, `activity_categories`, `user_activity_preferences` 모델이 있지만, 사용자 선호 테이블은 아직 추천 개인화에 연결되지 않았습니다.

## 장소 데이터 소스

| 소스 | 현재 사용 범위 |
|---|---|
| Kakao Local API | `food`, `cafe`, `culture`, `walk` 카테고리 검색, `drink`의 `술집` 키워드 검색, 위치·행정구역 검색 |
| TourAPI | `culture`, `entertainment`, `shopping` 후보. 데이터가 존재하는 최신 공개 기준월을 제한된 과거 범위에서 탐색 |
| 서울 문화행사 API | 현재 진행 중인 `culture` 행사와 전시, 운영시간 구조화, 장소 추천 및 선제 추천 |
| Popup JSON | 현재 진행 중인 `food`, `cafe`, `culture`, `entertainment`, `shopping` 팝업, 운영시간 구조화, 장소 추천 및 선제 추천 |

`walk`는 Kakao `AT4` 결과 중 산책에 적합한 세부 카테고리를 보수적으로 필터링합니다. TourAPI와 서울 문화행사 API가 실패하거나 빈 결과를 반환해도 이미 확보한 다른 소스 후보를 유지합니다.

## API

FastAPI에 현재 등록되는 endpoint입니다.

| Method | Path | 역할 | 등록 위치 |
|---|---|---|---|
| `GET` | `/` | 서버 기본 상태 확인 | `main.py` |
| `GET` | `/test-poi` | 서울 121개 POI 로딩 확인용 개발 endpoint | `main.py` |
| `POST` | `/recommend` | 자연어 조건 분석, 선제 추천 및 지역 추천 | `region_routes.py` |
| `POST` | `/recommend/places` | 선택 지역의 실제 장소 첫 페이지 추천 | `place_routes.py` |
| `POST` | `/recommend/places/more` | cursor cache의 다음 장소 페이지 반환 | `place_routes.py` |
| `POST` | `/recommend/places/validate-selection` | 선택 장소 체류시간과 예상 이동시간 사전검증 | `place_routes.py` |
| `POST` | `/recommend/course` | 실제 이동시간 기반 방문 순서 최적화 및 코스 판정 | `course_routes.py` |
| `POST` | `/auth/signup` | 회원가입, 성공 시 `201 Created` | `auth_routes.py` |
| `POST` | `/auth/login` | JWT Access Token 발급 | `auth_routes.py` |
| `GET` | `/users/me` | Bearer Token으로 현재 사용자 조회 | `auth_routes.py` |
| `GET` | `/openapi.json` | OpenAPI schema | FastAPI 자동 등록 |
| `GET` | `/docs` | Swagger UI | FastAPI 자동 등록 |
| `GET` | `/docs/oauth2-redirect` | Swagger OAuth2 redirect | FastAPI 자동 등록 |
| `GET` | `/redoc` | ReDoc UI | FastAPI 자동 등록 |

요청·응답 schema와 상세 예시는 서버 실행 후 Swagger UI의 `/docs`에서 확인할 수 있습니다.

## 성능 및 안정성

현재 적용된 최적화와 계측만 정리합니다.

- 11.5MB 상권 CSV의 지역 활동 점수를 process-memory에 캐시하고 호출자에게 DataFrame 복사본 반환
- 최종 추천 설명용 두 번째 LLM 호출을 deterministic template으로 대체
- 일반 지역 후보 최대 5개의 독립적인 이동시간 조회를 `ThreadPoolExecutor(max_workers=3)`로 제한 병렬화
- 시작 구간이 실패한 후보는 종료 구간을 호출하지 않아 기존 외부 API 호출 조건 유지
- `[PERFORMANCE]` 로그로 전체, intent LLM, proactive, 이동시간, 혼잡도, 메시지, 정적 데이터 로딩 구간 측정

process-memory cache는 프로세스 사이에 공유되지 않으며 서버가 재시작되면 초기화됩니다.

## 프로젝트 구조

```text
main.py                         FastAPI 앱 구성, router 등록, 성능 계측
models.py                       API 요청·응답 및 LLM 구조화 조건 모델

region_routes.py                지역 추천 API
place_routes.py                 장소 추천·pagination·선택 검증 API
course_routes.py                코스 계산 API
auth_routes.py                  회원가입·로그인·현재 사용자 API

region_recommendation_service.py 지역 후보 평가와 최종 지역 추천
proactive_recommendation_service.py 종료 임박 timely/detour 선제 추천
place_recommendation_service.py  Kakao·TourAPI·문화행사·Popup 장소 통합
place_recommendation_cache.py    장소 추천 cursor pagination cache
place_ranking.py                 장소 거리 및 공간 선호 soft scoring
place_space.py                   공통 실내·야외 분류
place_availability.py            예상 도착시간 기준 운영 가능 여부 계산

conditions.py                    위치·시간 조건 해석
candidate_filter.py              지역 후보 거리·시간 가능성 처리
ranking.py                       지역 활동·이동·혼잡도 점수 계산
activity_score.py                상권 데이터 기반 지역별 활동 점수와 캐시
congestion_service.py            서울 실시간·예측 혼잡도 조회
poi.py                           서울 121개 지역 후보 로딩
map_service.py                   Kakao 위치 검색과 도보·대중교통·차량 이동시간

popup_service.py                 Popup JSON 로딩·검증·정규화
seoul_culture_service.py         서울 문화행사 조회·캐시·운영시간 정규화
tour_service.py                  TourAPI 기준월 탐색과 관광지 조회

stay_time_validation.py          장소 선택 단계 체류·예상 이동시간 검증
activity_duration_policy.py      활동별 최소·기본 체류시간
course_order_optimizer.py        완전한 방문 순서 생성과 최적 순서 선택
route_leg_builder.py             시작·장소·종료 directed leg 생성
route_travel_time.py             실제 이동시간 조회와 request-level leg cache
course_time_evaluator.py         이동·체류시간 합산 및 코스 상태 판정

llm_service.py                   LLM V1.4 intent parser 연결과 안내문 template
LLM/LLM_V1_4_FREEZE/             16-field intent parser와 resilience freeze

database.py                      SQLAlchemy engine, SessionLocal, get_db
db_models.py                     사용자·선호·활동 SQLAlchemy 모델
auth.py                          Argon2 비밀번호와 JWT 처리

data/                            POI·상권·Popup 데이터
scripts/                         POI 좌표 생성 보조 스크립트
tests/                           서비스 및 API 회귀 테스트
requirements.txt                 고정된 직접 Python 의존성
koala_schema.sql                 MySQL 8 테이블과 활동 카테고리 seed
```

## 실행 환경 준비

### 1. Python 의존성

현재 검증 환경은 Python 3.14입니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 환경변수

예제 파일을 복사한 뒤 로컬 전용 비밀번호와 필요한 API 키를 설정합니다. 기존 `.env`와 실제 비밀값은 저장소에 커밋하지 않습니다.

```powershell
Copy-Item .env.example .env
```

`MYSQL_PASSWORD`와 `DATABASE_URL`의 비밀번호는 같아야 합니다. 비밀번호에 URL 예약 문자가 있으면 `DATABASE_URL`에서 URL encoding이 필요합니다.

### 3. Docker MySQL

로컬 DB는 MySQL 8.4 LTS, `utf8mb4`, 영속 volume으로 실행합니다.

```powershell
docker compose up -d
docker compose ps
```

Docker healthcheck가 `healthy`가 된 뒤 migration을 실행합니다.

### 4. Migration과 필수 seed

신규 DB의 현재 schema는 Alembic으로 생성하고, 서비스 필수 reference data인 7개 활동 카테고리는 별도 idempotent seed로 준비합니다.

```powershell
alembic upgrade head
python -m scripts.seed_activity_categories
```

기존 `koala_schema.sql`로 이미 생성된 DB에는 최초 한 번 schema가 현재 모델과 같은지 확인한 후 migration을 실행하지 말고 기준 revision만 기록합니다.

```powershell
alembic stamp head
python -m scripts.seed_activity_categories
```

`koala_schema.sql`은 기존 수동 초기화와 비교 확인을 위해 유지합니다. 신규 환경의 표준 경로는 Alembic입니다. 서버 startup에서 `create_all()`이나 자동 seed를 실행하지 않습니다.

LLM resilience 선택 설정:

```dotenv
LLM_TOTAL_DEADLINE_SECONDS=
LLM_FIRST_ATTEMPT_TIMEOUT_SECONDS=
LLM_RETRY_DELAY_SECONDS=
LLM_MAX_ATTEMPTS=
LLM_CIRCUIT_FAILURE_THRESHOLD=
LLM_CIRCUIT_OPEN_SECONDS=
LLM_RESULT_CACHE_ENABLED=
LLM_RESULT_CACHE_TTL_SECONDS=
LLM_RESULT_CACHE_PATH=
LLM_RUNTIME_LOG_PATH=
```

선택 설정을 생략하면 Freeze 모듈의 기본값을 사용합니다. 기본 LLM 결과 캐시는 `.runtime_cache/` 아래에 생성됩니다.

### 5. 서버 실행

```powershell
uvicorn main:app --reload
```

- API: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`

### 로컬 DB 초기화

로컬 테스트 데이터를 포함해 DB를 완전히 비우려면 컨테이너와 volume을 삭제한 뒤 다시 migration/seed를 실행합니다. 이 명령은 로컬 DB 전체를 삭제하므로 공용·운영 DB에서는 사용하지 않습니다.

```powershell
docker compose down -v
docker compose up -d
alembic upgrade head
python -m scripts.seed_activity_categories
```

### 공용 개발 DB와 AWS RDS 원칙

- 로컬, 공용 개발, 운영 DB는 서로 다른 인스턴스와 `DATABASE_URL`을 사용합니다.
- 공용 개발 DB에는 개발자별 계정을 발급하고 migration 계정과 앱 계정을 분리합니다.
- 앱 계정에는 schema 변경 권한을 주지 않고 필요한 DML 권한만 부여합니다.
- 운영 credential은 배포 secret manager에서 주입하며 `.env`나 저장소에 넣지 않습니다.
- 공용 개발·RDS에도 동일하게 `alembic upgrade head`와 seed 명령을 사용합니다.
- 테스트 데이터 초기화는 별도 개발 DB에서만 수행하며 운영 데이터에 reset 명령을 사용하지 않습니다.

## 테스트

전체 테스트:

```powershell
python -m pytest -q
```

개별 unittest 실행도 가능합니다.

```powershell
python -m unittest discover -s tests -v
```

2026-09-08 현재 실제 실행 결과:

```text
243 passed, 73 subtests passed
```

FastAPI `TestClient`에서 Starlette deprecation warning 1건이 발생하지만 테스트 실패는 없습니다.

## MVP v2 주요 변경사항

MVP v1의 지역 추천 → 장소 추천 → 코스 생성 흐름을 유지하면서 다음 기능이 추가되었습니다.

- Kakao·TourAPI에 서울 문화행사와 Popup 장소 소스 통합
- `walk`, `drink`를 포함한 7개 활동의 실제 장소 추천
- 활동별 round-robin과 cursor 기반 추가 장소 pagination
- 공통 `operation_schedule`과 예상 도착시간 기반 availability
- 종료 임박 `timely` 및 제한적인 `detour` 선제 추천
- `recommendation_context`로 다음 API에 필요한 해석 결과 전달
- 실내·야외 metadata와 사용자 공간 선호 soft scoring
- 선택 장소 최대 6개, `preferred_first`, directed-leg cache 기반 코스 최적화
- MySQL·SQLAlchemy 및 JWT 회원가입·로그인
- 정적 활동 점수 캐시, deterministic 추천 문구, bounded travel concurrency
- `/recommend` 구간별 성능 계측

## 현재 MVP 범위

현재 구현에 포함되지 않은 항목:

- 사용자 선호 DB를 이용한 추천 개인화
- OAuth, Refresh Token, 이메일 인증과 비밀번호 재설정
- Redis 기반 분산 pagination/session cache
- 날씨 기반 실내·야외 점수 조정
- 공휴일 판정 API
- availability를 이용한 장소 자동 제외 또는 코스 재최적화
- 선제 추천 수락·거절 이력 저장

이 항목들은 현재 동작을 설명하는 기능이 아니라 향후 확장 범위입니다.

## 데이터 출처

- 서울 주요 121장소: 서울 열린데이터광장, 공공누리 제1유형(출처표시)
- 서울 혼잡도 및 문화행사: 서울 열린데이터광장 API
- 장소·위치·경로: Kakao Local 및 Kakao Mobility API
- 관광 POI: 한국관광공사 TourAPI
- Popup: 프로젝트에 포함된 정적 스냅샷 JSON

외부 데이터와 API의 이용조건 및 출처표시 정책은 각 제공기관 정책을 따릅니다.
