# KOALA Backend

KOALA는 사용자의 자연어 요청, 현재 위치, 가용 시간, 이동수단 등을 바탕으로 서울에서 방문하기 적합한 지역과 실제 장소를 추천하고, 선택한 장소의 실제 이동시간을 기준으로 방문 코스를 구성하는 FastAPI 백엔드입니다.

지역 추천에서는 기존 서울 주요 121개 POI와 서울 행정동 기반 후보를 함께 평가하며, 행정동 후보에는 생활인구 기반 D-4 머신러닝 모델의 상대 혼잡도 예측을 적용합니다.

---

## 주요 추천 흐름

```text
사용자 자연어 요청 + GPS
        ↓
LLM 의도 구조화
        ↓
시작 위치 / 종료 위치 / 시간창 / 활동 / 이동수단 해석
        ↓
종료 임박 팝업·문화행사 선제 추천
        ↓
지역 후보 생성
 ├─ 서울 주요 121 POI
 └─ 좌표가 확인된 421개 행정동
        ↓
거리 및 우회거리 계산
        ↓
활동 적합도 평가
        ↓
실제 이동시간 계산
        ↓
혼잡도 평가
 ├─ 121 POI: 서울 도시데이터 혼잡도
 └─ 421 행정동: D-4 생활인구 ML 상대 혼잡도
        ↓
활동 + 이동 + 혼잡도 최종 점수 계산
        ↓
통합 정렬 및 지역 추천
        ↓
선택 지역 주변 실제 장소 추천
        ↓
장소 선택 사전검증
        ↓
실제 이동시간 기반 방문 순서 최적화
        ↓
FEASIBLE / INFEASIBLE 코스 반환
```

---

## 주요 기능

### 1. 자연어 의도 구조화

사용자의 자연어 요청을 구조화된 추천 조건으로 변환합니다.

주요 조건:

* 시작 위치
* 목적 위치
* 종료 위치
* 시작·종료 시간
* 희망 체류시간
* 활동 유형
* 이동수단
* 동행 유형
* 예산
* 실내·실외 선호

지원 활동:

* `food`
* `cafe`
* `walk`
* `culture`
* `entertainment`
* `shopping`
* `drink`

지원 이동수단:

* `auto`
* `public_transit`
* `walk`
* `car`

LLM이 생성한 결과는 `StructuredConditions`로 검증하며, 추천 결과 설명은 추가 LLM 호출 없이 백엔드의 deterministic template을 사용합니다.

---

## 2. 종료 임박 선제 추천

일반 지역 추천과 함께 현재 위치에서 실제로 방문 가능한 팝업 또는 서울 문화행사를 최대 1개 제안할 수 있습니다.

주요 기준:

* 오늘부터 3일 이내 종료되는 행사
* 현재 위치 기준 직선거리 후보 탐색
* 상위 후보에 실제 이동시간 적용
* 운영시간과 최소 체류시간 확인
* 다음 일정이 존재할 경우 이동시간과 안전 버퍼 반영

선제 추천 유형:

* `timely`
* `detour`

외부 행사 API가 실패하거나 결과가 없어도 일반 지역 추천은 계속 진행됩니다.

---

## 3. 서울 지역 추천

KOALA의 지역 추천은 두 종류의 후보군을 함께 사용합니다.

### 서울 주요 121 POI

서울 주요 장소 121개를 기준으로 다음 요소를 평가합니다.

* 현재 위치 또는 목적 위치와의 거리
* 종료 위치가 있을 경우 우회 동선
* 실제 이동시간
* 사용자의 시간창
* 활동 적합도
* 서울 도시데이터 기반 혼잡도

### 행정동 기반 421 후보

서울 행정동 데이터 중 좌표가 확인되고 추천에 사용할 수 있는 421개 행정동을 별도의 후보군으로 사용합니다.

421 후보는 다음 순서로 처리됩니다.

```text
421 행정동
    ↓
거리 / 우회거리 계산
    ↓
상위 후보 선정
    ↓
활동 적합도 반영
    ↓
최대 5개 실제 이동시간 조회
    ↓
후보별 예상 도착시각 계산
    ↓
D-4 ML 상대 혼잡도 예측
    ↓
최종 점수 계산
```

421 행정동 추천은 일반 추천 경로에서 사용하며, 사용자가 특정 목적 지역을 직접 지정한 경로에서는 기존 121 POI 기반 로직을 유지합니다.

---

## 4. 활동 적합도

상권 데이터를 행정동 단위로 집계하고 추천 후보에 연결하여 활동별 적합도를 계산합니다.

주요 활동:

* `food`
* `cafe`
* `drink`
* `entertainment`

행정동별 업종 수를 기준으로 상대 순위를 계산하여 1~5점의 활동 점수로 변환합니다.

121 POI와 421 행정동은 서로 다른 후보 모집단을 사용하므로 각각의 후보군 안에서 활동 점수가 계산됩니다.

---

## 5. D-4 생활인구 ML 상대 혼잡도

421 행정동 후보에는 생활인구 기반 머신러닝 모델을 사용합니다.

이 값은 서울 도시데이터의 공식 혼잡도 등급이 아니라, 과거 생활인구 패턴을 이용해 계산한 상대적인 생활인구 활동·혼잡 신호입니다.

### 모델 입력

D-4 Provider는 예측 기준시각을 기준으로 다음 과거 시점을 사용합니다.

```text
T - 96시간
T - 168시간
T - 336시간
```

운영 데이터는 서울 생활인구 API에서 수집하여 다음 형태로 관리합니다.

```text
datetime
행정동코드
생활인구합계
```

### 예측 Horizon

후보별 실제 이동시간으로 예상 도착시각을 계산하고, 도착시각에 따라 +1~+6 horizon 중 하나를 선택합니다.

### 예측 클래스

모델은 상대 생활인구 비율을 네 구간으로 예측합니다.

```text
p0 : ratio <= 0.80
p1 : 0.80 < ratio <= 1.20
p2 : 1.20 < ratio <= 1.50
p3 : ratio > 1.50
```

상대 혼잡도 index:

```text
relative_congestion_index
= 0*p0 + 1*p1 + 2*p2 + 3*p3
```

추천 점수 계산에 사용하는 ML 혼잡도 점수:

```text
congestion_score
= p0*5 + p1*4 + p2*2 + p3*1
```

ML 예측이 불가능한 경우 후보를 제거하지 않고 중립값 `3.0`을 사용합니다.

주요 상태:

* `ok`
* `unsupported_region`
* `insufficient_history`
* `population_source_failure`
* `inference_failure`

---

## 6. D-4 모델 패키징

D-4 추론에 필요한 모델과 Provider는 백엔드 저장소 안에 포함되어 있습니다.

```text
ml/
└─ d4_direct/
   ├─ d4_direct_h1.joblib
   ├─ d4_direct_h2.joblib
   ├─ d4_direct_h3.joblib
   ├─ d4_direct_h4.joblib
   ├─ d4_direct_h5.joblib
   ├─ d4_direct_h6.joblib
   ├─ d4_direct_metadata.joblib
   ├─ d4_direct_provider.py
   ├─ standalone_inference.py
   └─ local_resd_support_master.csv
```

기본적으로 백엔드 내부의 `ml/d4_direct`를 사용합니다.

필요할 경우 환경변수 `D4_DIRECT_ARTIFACT_DIR` 또는 명시적인 artifact directory 주입으로 다른 경로를 사용할 수 있습니다.

---

## 7. 생활인구 운영 데이터

`population_history.py`에서 서울 생활인구 데이터를 수집·정규화하고 D-4 모델에 필요한 history를 관리합니다.

주요 기능:

* 일 단위 생활인구 수집
* 데이터 정규화
* 일별 데이터 검증
* 중복 없는 history 갱신
* atomic CSV 저장
* 최근 60일 유지
* D-4 추론에 필요한 시점 선택

정상적인 하루 데이터는 서울 427개 행정동 × 24시간을 기준으로 검증합니다.

```text
427 × 24 = 10,248 rows
```

수동 수집 예시:

```powershell
py -3.14 population_history.py 2026-09-13
```

운영 history 파일은 다음 위치에 생성됩니다.

```text
data/population_history.csv
```

이 파일은 운영 중 생성되는 데이터이므로 Git에 포함하지 않습니다.

### 시간 처리

실제 FastAPI 요청은 `Asia/Seoul` timezone-aware datetime을 사용합니다.

D-4 모델과 생활인구 history는 서울 현지시각 기준의 timezone-naive hourly timestamp를 사용하므로, ML 추론 시 서울 현지 clock time은 유지하고 timezone 정보만 제거한 뒤 hour 단위로 정규화합니다.

예:

```text
2026-09-17T15:28:00+09:00
        ↓
2026-09-17 15:28:00
        ↓
2026-09-17 15:00:00
```

UTC 시간으로 변환하지 않습니다.

---

## 8. 지역 최종 점수

활동 적합도가 존재하는 경우:

```text
final_score
= activity_score × 0.5
+ travel_score × 0.3
+ congestion_score × 0.2
```

활동 적합도를 사용할 수 없는 경우:

```text
final_score
= travel_score × 0.6
+ congestion_score × 0.4
```

121 POI와 421 행정동 후보에 각각 필요한 평가를 적용한 뒤 `final_score`를 기준으로 통합 정렬합니다.

응답에서는 후보 출처를 구분할 수 있습니다.

```text
candidate_source = "poi121"
candidate_source = "local_resd"
```

---

## 9. 실제 장소 추천

선택한 지역 중심의 실제 장소를 여러 데이터 소스에서 수집합니다.

* Kakao Local API
* TourAPI
* 서울 문화행사 API
* Popup 데이터

중복 제거 후 거리, 활동, 실내·실외 선호 등을 반영하여 추천합니다.

장소 metadata:

* `space_type`
* `space_type_confidence`
* `space_type_basis`

`space_preference`는 hard filter가 아니라 soft scoring으로 사용합니다.

---

## 10. 장소 Pagination

장소 추천은 cursor 기반 pagination을 지원합니다.

* 첫 페이지 최대 6개 장소
* 다음 후보는 process-memory cursor cache에 저장
* TTL 15분
* `/recommend/places/more` 호출 시 외부 장소 API를 다시 호출하지 않음
* 만료된 cursor: `410`
* 존재하지 않는 cursor: `404`

여러 행정동을 요청한 경우 특정 행정동에 결과가 편중되지 않도록 round-robin 방식으로 결과를 구성합니다.

---

## 11. 장소 선택 사전검증

사용자가 장소를 선택하면 최종 코스 계산 전에 다음 내용을 검증합니다.

* 코스당 1~6개 장소
* 활동별 최소·기본 체류시간
* 사용자 지정 체류시간
* 거리 기반 예상 이동시간
* 예상 방문 순서
* 총 가용시간과 예상 이동·체류시간 비교

선택 단계의 예상 이동시간은 빠른 피드백을 위한 heuristic이며 hard rejection 기준으로 사용하지 않습니다.

최종 가능 여부는 실제 이동시간을 사용하는 코스 계산 단계에서 결정합니다.

---

## 12. 코스 최적화

선택된 모든 장소를 포함하는 방문 순서를 계산합니다.

* 시작 위치 고정
* 종료 위치가 있으면 종료 위치 고정
* `preferred_first=true` 장소가 있으면 첫 방문지로 고정
* 최대 6개 장소 permutation 평가
* 구간별 실제 이동시간 조회
* request-level directed leg cache 사용
* 실제 이동시간이 가장 짧은 유효 순서 선택

이동시간과 체류시간을 합산하여 최종 코스를 판정합니다.

```text
FEASIBLE
INFEASIBLE
```

---

## 13. 예상 운영시간 / Availability

`departure_datetime`이 존재하면 방문 순서에 따라 장소별 예상 도착시간을 계산합니다.

주요 상태:

* `open`
* `closed`
* `not_yet_open`
* `unknown`
* `event_not_started`
* `event_ended`

운영시간 정보가 없거나 신뢰하기 어려운 장소는 임의로 제외하지 않고 `unknown`으로 처리합니다.

---

## 14. 회원 및 인증

* MySQL
* SQLAlchemy
* Alembic
* Argon2 비밀번호 해시
* JWT HS256 Access Token
* Bearer Token 기반 사용자 조회

주요 테이블:

* `users`
* `user_preferences`
* `activity_categories`
* `user_activity_preferences`

현재 추천 API는 로그인 없이 사용할 수 있으며 사용자 선호 DB는 향후 추천 개인화를 위한 구조로 준비되어 있습니다.

---

# API

| Method | Path                                   | 역할                  |
| ------ | -------------------------------------- | ------------------- |
| `GET`  | `/`                                    | 서버 기본 상태 확인         |
| `GET`  | `/test-poi`                            | 서울 121 POI 로딩 확인용   |
| `POST` | `/recommend`                           | 자연어 조건 분석 및 지역 추천   |
| `POST` | `/recommend/places`                    | 선택 지역 실제 장소 추천      |
| `POST` | `/recommend/places/more`               | 다음 장소 페이지 반환        |
| `POST` | `/recommend/places/validate-selection` | 선택 장소 사전검증          |
| `POST` | `/recommend/course`                    | 실제 이동시간 기반 코스 최적화   |
| `POST` | `/auth/signup`                         | 회원가입                |
| `POST` | `/auth/login`                          | JWT Access Token 발급 |
| `GET`  | `/users/me`                            | 현재 사용자 조회           |
| `GET`  | `/openapi.json`                        | OpenAPI schema      |
| `GET`  | `/docs`                                | Swagger UI          |
| `GET`  | `/redoc`                               | ReDoc               |

상세 request/response schema는 서버 실행 후 Swagger UI에서 확인할 수 있습니다.

---

# 프로젝트 구조

```text
main.py
    FastAPI 앱 구성, dependency 연결, router 등록

models.py
    API 요청·응답 및 구조화 조건 모델

region_routes.py
    지역 추천 API

region_recommendation_service.py
    121 POI + 421 행정동 후보 평가 및 통합 지역 추천

local_resd_candidates.py
    행정동 후보 로딩 및 활동 적합도 데이터 구성

local_resd_congestion_adapter.py
    D-4 Provider 연결, horizon 및 ML fallback 처리

population_history.py
    서울 생활인구 수집·검증·history 관리

ranking.py
    지역 활동·이동·혼잡도 점수 계산

activity_score.py
    상권 데이터 기반 활동 점수

congestion_service.py
    서울 도시데이터 실시간·예측 혼잡도 조회

poi.py
    서울 주요 121 POI 로딩

candidate_filter.py
    지역 후보 거리·시간 가능성 처리

conditions.py
    위치·시간 조건 해석

map_service.py
    위치 검색 및 이동시간 처리

proactive_recommendation_service.py
    종료 임박 timely / detour 선제 추천

place_routes.py
    장소 추천·pagination·선택 검증 API

place_recommendation_service.py
    Kakao·TourAPI·문화행사·Popup 장소 통합

place_recommendation_cache.py
    장소 cursor pagination cache

place_ranking.py
    장소 거리 및 공간 선호 scoring

place_space.py
    실내·실외 분류

place_availability.py
    예상 도착시간 기준 운영 가능 여부 계산

stay_time_validation.py
    장소 선택 단계 체류·예상 이동시간 검증

activity_duration_policy.py
    활동별 최소·기본 체류시간

course_routes.py
    코스 계산 API

course_order_optimizer.py
    방문 순서 생성 및 최적 순서 선택

route_leg_builder.py
    시작·장소·종료 directed leg 생성

route_travel_time.py
    실제 이동시간 조회 및 request-level cache

course_time_evaluator.py
    이동·체류시간 합산 및 코스 판정

popup_service.py
    Popup 데이터 처리

seoul_culture_service.py
    서울 문화행사 조회

tour_service.py
    TourAPI 관광 POI 조회

llm_service.py
    LLM intent parser 연결 및 안내문 처리

database.py
    SQLAlchemy engine / Session

db_models.py
    사용자 및 선호 SQLAlchemy 모델

auth.py
    Argon2 / JWT 인증

ml/d4_direct/
    D-4 ML 모델 및 standalone Provider

data/
    POI, 상권, Popup 등 프로젝트 데이터

scripts/
    데이터 생성 및 DB seed 보조 스크립트

tests/
    서비스 및 API 테스트
```

---

# 실행 환경

## Python

현재 검증 환경:

```text
Python 3.14
```

가상환경 생성:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

ML 실행에 필요한 주요 패키지도 `requirements.txt`에 포함되어 있습니다.

```text
pandas==3.0.3
joblib==1.6.0
numpy==2.4.4
lightgbm==4.7.0
scikit-learn==1.9.1
```

---

## 환경변수

예제 환경파일을 복사합니다.

```powershell
Copy-Item .env.example .env
```

프로젝트 기능에 따라 다음과 같은 외부 서비스 설정이 필요합니다.

* Kakao API
* 서울 Open API
* LLM API
* MySQL / `DATABASE_URL`

실제 API Key와 비밀번호는 저장소에 커밋하지 않습니다.

D-4 artifact 경로를 별도로 지정할 경우:

```dotenv
D4_DIRECT_ARTIFACT_DIR=
```

기본값은 저장소 내부 `ml/d4_direct`입니다.

---

# DB 실행

로컬 DB는 MySQL 8 계열을 기준으로 사용합니다.

```powershell
docker compose up -d
docker compose ps
```

신규 DB:

```powershell
alembic upgrade head
python -m scripts.seed_activity_categories
```

기존 `koala_schema.sql`로 생성한 DB를 사용할 경우 현재 schema와 일치하는지 확인한 뒤 필요하면:

```powershell
alembic stamp head
python -m scripts.seed_activity_categories
```

---

# 서버 실행

```powershell
uvicorn main:app --reload
```

기본 주소:

```text
API
http://127.0.0.1:8000

Swagger UI
http://127.0.0.1:8000/docs
```

---

# 생활인구 데이터 갱신

D-4 ML 예측을 사용하려면 필요한 과거 생활인구 데이터가 존재해야 합니다.

예:

```powershell
py -3.14 population_history.py YYYY-MM-DD
```

생성 파일:

```text
data/population_history.csv
```

이 파일은 Git에 포함하지 않습니다.

---

# 테스트

전체 테스트:

```powershell
py -3.14 -m pytest -q
```

2026-09-17 기준 최종 검증 결과:

```text
401 passed, 1 warning, 128 subtests passed
```

현재 warning 1건은 FastAPI `TestClient`에서 사용하는 Starlette/httpx 관련 deprecation warning이며 테스트 실패는 아닙니다.

D-4 모델 artifact smoke test와 생활인구 history, timezone-aware 운영시간 처리에 대한 회귀 테스트도 전체 테스트에 포함되어 있습니다.

---

# 현재 구현 범위

현재 구현된 주요 기능:

* 자연어 기반 추천 조건 구조화
* 서울 주요 121 POI 추천
* 서울 421 행정동 후보 추천
* 121 + 421 통합 ranking
* 상권 기반 활동 적합도
* 서울 도시데이터 기반 121 POI 혼잡도
* D-4 ML 기반 421 행정동 상대 혼잡도
* 후보별 실제 도착시각 기반 ML horizon 선택
* 실제 장소 통합 추천
* cursor pagination
* 실내·실외 선호 soft scoring
* 종료 임박 팝업·문화행사 선제 추천
* 장소 선택 사전검증
* 최대 6개 장소 방문 순서 최적화
* 실제 이동시간 기반 최종 코스 판정
* 장소 예상 운영시간 계산
* MySQL / SQLAlchemy / Alembic
* 회원가입 / 로그인 / JWT
* 사용자 선호 DB 구조

향후 확장 범위:

* 사용자 선호 DB와 추천 알고리즘의 실제 개인화 연결
* OAuth / Refresh Token
* Redis 기반 분산 cache
* 실제 사용자 피드백 기반 추천 보정
* 운영 환경의 생활인구 자동 수집 스케줄링

---

# 데이터 출처

* 서울 주요 장소 및 도시데이터: 서울 열린데이터광장
* 서울 생활인구: 서울 열린데이터광장 생활인구 데이터
* 위치 및 장소 검색: Kakao Local API
* 이동시간: 프로젝트에서 사용하는 Kakao 이동 관련 API
* 관광 POI: 한국관광공사 TourAPI
* 문화행사: 서울시 문화행사 데이터
* Popup: 프로젝트 내부 정적 데이터

외부 데이터와 API 사용 시 각 제공기관의 이용조건 및 출처표시 정책을 따릅니다.
