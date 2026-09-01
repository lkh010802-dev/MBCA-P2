# Popup Crawler 개발 이력
## v0.1 → v1.0.0

이 문서는 서울 팝업스토어 데이터 수집 프로젝트가 초기 실험 단계에서 내부 운영 가능한 v1.0.0까지 어떻게 발전했는지를 정리한 개발 이력 문서입니다.

프로젝트의 핵심 목표는 단순 크롤링이 아니라 아래 전체 흐름을 안정적으로 자동화하는 것입니다.

```text
다중 소스 수집
→ RAW 원본 보존
→ 정규화
→ 팝업 / 비팝업 판정
→ 상세페이지 보강
→ 중복 탐지 및 병합
→ Persistent popup_id
→ Master DB
→ ACTIVE / UPCOMING / ENDED / UNVERIFIED 관리
→ 일일 변화 추적
→ Backend CSV 생성
→ 자동 스케줄 실행
```

---

# 1. 프로젝트 초기 목표

초기에는 서울 팝업 정보를 여러 사이트에서 자동으로 가져오는 것이 목표였습니다.

하지만 개발이 진행되면서 단순히 데이터를 많이 모으는 것보다 아래 문제가 더 중요하다는 것을 확인했습니다.

- 같은 팝업이 여러 사이트에 중복 등록됨
- 사이트마다 이름, 주소, 설명의 품질이 다름
- 팝업이 아닌 공연, 클래스, 상설매장, 프로모션 등이 섞임
- 목록 페이지 정보만으로 판별하기 어려운 데이터가 존재함
- 사이트의 원천 데이터 자체가 잘못된 경우가 있음
- 매일 다시 실행했을 때 동일 팝업의 ID가 유지되어야 함
- 사이트가 일시적으로 데이터를 누락했다고 바로 종료 처리하면 안 됨
- 백엔드가 사용할 수 있는 하나의 일일 결과물이 필요함

따라서 프로젝트는 점차 **다중 소스 팝업 데이터 통합 파이프라인**으로 발전했습니다.

---

# 2. 버전별 개발 이력

## v0.1 — DayForYou 초기 크롤러

### 목표
DayForYou에서 서울 팝업 목록을 자동으로 가져오는 첫 크롤러 구현.

### 주요 작업
- DayForYou 목록 페이지 요청
- 팝업 카드 DOM 분석
- 팝업 이름, 주소, 기간, source_id 추출
- 서울 데이터 필터링
- JSON/JSONL 형태 저장

### 초기 문제
초기에는 평면 텍스트 기반 파싱을 사용하면서 카드 간 필드가 섞이는 문제가 있었습니다.

### 개선
실제 DOM 구조를 확인한 뒤 `li.schedule_box` 단위 카드 파싱으로 변경했습니다.

```text
HTML 전체 텍스트 파싱
→ 카드 DOM 단위 파싱
```

이 단계에서 이후 모든 소스에 공통으로 적용되는 원칙이 정해졌습니다.

> 추측보다 실제 DOM을 먼저 확인한다.

---

## v0.2 — 정규화와 서울 필터 안정화

### 주요 작업
- 서울 주소 판정 로직 강화
- RAW / normalized 데이터 분리
- 주소 정규화
- 서울 자치구 추출
- 날짜 정규화
- 운영기간 계산
- 데이터 품질 점수
- 팝업 가능성 점수 도입

### 중요한 수정

초기 서울 필터가 `중구` 같은 자치구 이름만 보고 판단하면서 대구 중구, 부산 중구까지 서울로 오인하는 문제가 있었습니다.

이를 아래처럼 변경했습니다.

```text
주소가
서울
서울시
서울특별시

로 시작하는 경우만 서울로 인정
```

### 설계 원칙
원본 데이터의 오류와 크롤러 오류를 구분하기 위해 다음 필드를 분리했습니다.

```text
name_raw
name

address_raw
address
```

---

## v0.3 — 상세페이지 기반 보강

### 목표
목록 정보만으로 판단하기 어려운 데이터에 대해 상세페이지를 추가 수집.

### 주요 작업
- 검토 대상만 상세페이지 조회
- HTML 캐시 저장
- 상세 제목
- 상세 주소
- 기간
- 해시태그
- 설명
- 공식 링크
- 운영 정보 추출

### 발견된 문제
처음에는 거의 모든 상세 데이터가 `SPARSE_DETAIL`로 판단되었습니다.

원인은 데이터 부족이 아니라 **파서가 실제 DOM과 맞지 않았기 때문**이었습니다.

특히 주소가:

```text
copyLocation('서울 ...')
```

형태였는데 기존 파서가 다른 onclick 구조를 찾고 있었습니다.

### 결과
실제 DOM에 맞게 수정한 뒤:

```text
상세 주소 누락: 0건
```

까지 개선되었습니다.

---

## v0.3.1 — 규칙 기반 POPUP / NON_POPUP 강화

상세정보를 이용해 명확한 데이터는 LLM 없이 자동 판정하도록 강화했습니다.

실제 검증 결과:

```text
입력 검토 후보: 68건
팝업 자동확정: 14건
비팝업 자동제외: 46건
진짜 애매한 후보: 8건
전체 대비 검토율: 약 1.7%
```

이 시점부터 프로젝트의 핵심 원칙이 확정되었습니다.

> LLM은 전체 데이터를 판단하는 엔진이 아니라 마지막 애매한 데이터만 처리하는 fallback이다.

---

## v0.4 — Fresh Crawl + LLM Fallback

### 주요 작업
- 오늘 기준 전체 fresh crawling
- 기존 캐시에 의존하지 않는 검증 모드
- dry-run 기본값
- 명시적으로 실행할 때만 OpenAI 호출
- Structured Output 기반 LLM 분류
- batch 처리
- confidence threshold 도입

### 실제 fresh 검증

```text
서울 전체: 420건
상세 재검토: 62건
상세 규칙 POPUP: 11건
상세 규칙 NON_POPUP: 44건
최종 LLM 후보: 7건
LLM 후보율: 1.7%
```

실제 API 호출:

```text
LLM 후보: 7
API 호출: 1회
NON_POPUP: 5
수동검토: 2
```

### 새로운 분류 상태 도입

수동검토 2건은 데이터 자체가 placeholder라 판단할 수 없었습니다.

이를 계기로 최종 분류 상태를 다음처럼 확장했습니다.

```text
POPUP
NON_POPUP
INSUFFICIENT_DATA
UNCERTAIN
```

---

## v0.5 — Popga 두 번째 소스 추가

### 목표
DayForYou 단일 소스에서 다중 소스 구조로 확장.

### 주요 작업
- Playwright 기반 Popga 공개 페이지 렌더링
- 무한 스크롤 대응
- 서울 후보 추출
- 기간 / 상태 / 카테고리 수집
- Popga 상세페이지 수집
- 공통 schema 방향 정립

### 수집 원칙
- 로그인 사용 안 함
- 비공개 API 사용 안 함
- anti-bot 우회 안 함
- 공개 페이지 저빈도 수집

---

## v0.5.x — Popga 상세 파서 및 판정 강화

Popga 상세 데이터에서 다음 정보를 안정적으로 확보하도록 개선했습니다.

- 상세 주소
- 상세 설명
- 원천 타입
- 날짜
- source_id
- 이미지
- 카테고리

또한 공연, 전시, 페스티벌, 일반 이벤트 등이 팝업으로 잘못 들어오는 것을 줄이기 위한 규칙을 지속적으로 강화했습니다.

---

## v0.6 — 다중 소스 구조 준비

이 시기에는 DayForYou + Popga 데이터를 공통 schema로 맞추고 이후 세 번째 소스를 추가할 수 있도록 구조를 정리했습니다.

핵심 방향:

```text
Source별 RAW
→ Source별 Normalizer
→ Common Record
→ Classification
→ Duplicate Candidate
→ Canonical
```

---

## v0.7 — Popply 세 번째 소스 추가

### 주요 작업
- Popply ACTIVE / UPCOMING 공개 목록 수집
- 상세페이지 전체 수집
- 주소 / 설명 / 예약정보 추출
- 온라인 기간과 실제 오프라인 팝업 기간 구분

실제 v0.7.1 결과:

```text
서울 후보: 154건
ACTIVE: 116
UPCOMING: 38

상세 요청: 154
성공: 154
실패: 0
주소 누락: 0
이름 mismatch: 0
시작일 mismatch: 0
종료일 mismatch: 0
```

### 중요한 개선
Popply 설명에 온라인 판매기간과 오프라인 팝업기간이 같이 있는 경우:

```text
ONLINE
2026-08-27 ~ 09-17

OFFLINE POP-UP
2026-09-08 ~ 09-17
```

처럼 명확한 오프라인 기간이 있을 때 실제 물리 팝업 기간을 우선하도록 처리했습니다.

---

## v0.7.1 — 3-Source 통합 최초 성공

세 소스 전체를 처음 실제로 통합했습니다.

```text
DayForYou
+
Popga
+
Popply
↓
Common Schema
↓
Classification
↓
Duplicate Detection
↓
Canonical Merge
```

초기 통합 결과 예:

```text
원본 약 831건
팝업 판정 약 744건
Canonical 약 600개
```

같은 팝업을 여러 사이트가 제공하는 경우 단순 삭제하지 않고 필드별로 더 좋은 정보를 선택하도록 설계했습니다.

예:

```text
이름/기간 → 세 사이트 일치
주소      → 더 상세한 source
좌표      → Popga
설명      → Popply
이미지    → Popga
태그      → Popply
```

또한 각 필드의 source provenance를 유지했습니다.

---

# 3. v0.8 — 통합 안정화와 Master DB

## v0.8.0 — Persistent popup_id 도입

이전 Canonical ID는 실행마다 바뀔 수 있는 preview hash였습니다.

이를 영구 ID 구조로 변경했습니다.

```text
popup_xxxxxxxxxxxxxxxx
```

### 검증

첫 master 생성:

```text
Canonical: 596
신규 persistent ID: 596
```

동일 데이터를 재실행:

```text
기존 ID 재사용: 596
신규 ID: 0
```

즉 같은 팝업은 다음 실행에서도 동일한 `popup_id`를 유지합니다.

---

## Master DB 도입

```text
data/master/canonical_master.jsonl
```

을 도입해 일일 snapshot과 누적 상태를 분리했습니다.

### Lifecycle

```text
ACTIVE
UPCOMING
ENDED
UNVERIFIED
```

UNVERIFIED를 추가한 이유:

> 사이트에서 오늘 사라졌다는 이유만으로 바로 ENDED 처리하면 안 된다.

예:

```text
어제 존재
오늘 사이트에서 안 보임
종료일은 아직 안 지남

→ ENDED가 아니라 UNVERIFIED
```

---

## v0.8.1 — 명시적 수동 결정 재사용

자동 규칙으로 판단하기 위험한 일부 데이터는 사람이 한 번 결정한 뒤 다시 묻지 않도록 했습니다.

예:
- 일반 유료 전시
- 장기 플래그십 스토어

명시적 NON_POPUP 결정을 master에도 안전하게 반영하도록 수정했습니다.

결과:

```text
분류 REVIEW: 0
중복 REVIEW: 0
```

---

# 4. v0.9 — Daily Runner 운영 자동화

## v0.9.0 — run_daily 도입

기존에는 직접 다음을 순서대로 실행했습니다.

```text
DayForYou
Popga
Popply
Integration
```

이를 하나로 묶었습니다.

```text
run_daily.bat
```

### 흐름

```text
Fresh Crawl
→ Detail
→ Classification
→ Merge
→ Master Update
→ Daily Report
```

### Safety Gate
다음 상황에서는 master를 변경하지 않습니다.

- source 수집 실패
- 수집 건수 급감
- 상세페이지 실패율 과다
- classification REVIEW 발생
- duplicate REVIEW 발생
- canonical 결과 비정상

---

## v0.9.1 — 네트워크 및 실행환경 안정화

DayForYou `www` DNS 실패를 계기로:

```text
dayforyou.com
↔ www.dayforyou.com
```

fallback과 retry를 추가했습니다.

또 `.venv`가 없을 때 시스템 Python으로 조용히 fallback하는 문제를 개선했습니다.

---

## v0.9.2 — 속도 최적화

초기 Daily Runner는 약 13~15분 정도 소요됐습니다.

주요 병목:
- Popga 전체 상세 순차 조회
- Popply 전체 상세 순차 조회
- Popply browser wait

### 개선
- Popga / Popply 병렬 실행
- 상세 cache 재사용
- 신규 / UPCOMING / 변경 건만 live 조회
- Popply 이미지 / 미디어 / 폰트 차단
- 상세 진행률 출력
- subprocess unbuffered 출력

실제 결과:

```text
기존: 약 13분 29초
개선: 약 4분 17초
```

약 3배 이상 빨라졌습니다.

---

## v0.9.3 — Daily Change Tracking

전날 master와 오늘 데이터를 비교해 변화 리포트를 생성하도록 했습니다.

추적 항목:

```text
new
ended
reappeared
changed
unverified
source_changes
retired
```

예:

```text
신규 팝업
종료 팝업
다시 등장한 팝업
기간 변경
이름 변경
주소 변경
카테고리 변경
source 추가/제거
```

같은 날 동일 데이터를 다시 실행하면 변화가 중복 집계되지 않도록 처리했습니다.

---

## v0.9.4 — Popply Hydration 문제 대응

속도 최적화 이후 Popply 동적 페이지가 완전히 렌더링되기 전에 상세 HTML을 저장하는 문제가 발견되었습니다.

증상:

```text
detail_fetch_ok=True
그러나
title 없음
address 없음
description 없음
date 없음
```

### 개선
- 페이지 접근 성공과 데이터 완성도를 분리
- core detail 필드 완성 여부 검사
- DOM hydration 대기
- reload retry
- 과거 정상 cache 복구

또한:

```text
sources
sources_ever
```

를 분리해 오늘 source와 역대 source를 따로 관리하도록 했습니다.

---

## v0.9.5 — Backend CSV 도입

백엔드에 전달하기 쉬운 최종 파일을 추가했습니다.

```text
output/
├─ 20260901_popup.csv
├─ 20260902_popup.csv
└─ ...
```

### 특징
- `data/`는 내부 감사 / raw / master 용도
- `output/`은 백엔드 전달용
- 성공적으로 master가 commit된 경우에만 CSV 생성
- 실패한 실행은 정상 CSV를 덮어쓰지 않음
- UTF-8 BOM 사용

주요 CSV 컬럼:

```text
popup_id
name
brand
category
start_date
end_date
status
venue_name
address
district
latitude
longitude
description
reservation_url
official_url
image_url
tags
sources
source_count
confidence
first_seen_at
last_seen_at
last_verified_at
```

---

## v0.9.6 — Detail Quarantine

Popply 149건 중 1건의 상세 실패 때문에 전체 실행이 BLOCK되는 상황이 발생했습니다.

전체를 막는 대신 작은 오류는 격리하도록 변경했습니다.

```text
정상 데이터
→ integration 계속

일부 실패 데이터
→ detail_quarantine.jsonl
```

기본 정책:

```text
불완전 <= 2건
AND
불완전 비율 <= 2%

→ quarantine 후 계속

그 이상
→ 전체 BLOCK
```

---

## v0.9.7 — 운영 중복 판정 마무리

실제 운영 데이터에서 마지막으로 남은 중복 REVIEW를 분석해 명시적 결정을 추가했습니다.

예:
- 전체 페스티벌 내부의 일부 popup 코너
- 상설점 내부의 기간 한정 굿즈 페어

이들은 팝업 DB 기준으로 NON_POPUP 처리했습니다.

최종적으로:

```text
classification_review = 0
duplicate_review = 0
master_committed = True
```

상태에서 backend CSV 생성에 성공했습니다.

실제 예:

```text
Backend CSV:
output/20260901_popup.csv
```

---

# 5. v1.0.0 — 첫 내부 운영 / 배포 버전

v0.x에서 검증한 기능을 정리해 첫 운영 가능 버전으로 고정했습니다.

## 최종 기능

### Crawling
- DayForYou
- Popga
- Popply

### Parsing / Normalization
- RAW 원본 보존
- source별 parser
- 공통 schema
- 상세페이지 보강

### Classification
- POPUP
- NON_POPUP
- INSUFFICIENT_DATA
- UNCERTAIN
- deterministic rule 우선
- LLM fallback 최소 사용

### Duplicate / Merge
- 이름 similarity
- 주소
- 날짜 overlap
- source evidence
- provenance
- 명시적 review decision 재사용

### Persistent Identity
- Persistent `popup_id`
- source refs 기반 identity
- 기존 ID 재사용
- 신규 데이터만 새 ID 발급

### Master DB
- ACTIVE
- UPCOMING
- ENDED
- UNVERIFIED
- history 보존

### Daily Change Tracking
- new
- ended
- reappeared
- changed
- unverified
- source changes
- retired

### Backend Output

```text
output/YYYYMMDD_popup.csv
```

### Safety
- source failure gate
- detail quality gate
- review gate
- quarantine
- master history backup
- 성공한 경우에만 backend CSV 생성

### Performance
- Popga / Popply 병렬 실행
- 상세 cache
- live refresh
- browser resource filtering
- duplicate candidate prefilter

### Automation
- `run_daily.bat`
- `run_daily_scheduled.bat`
- Windows Task Scheduler 지원
- 매일 오전 08:00 자동실행 등록 / 확인 / 제거

### Distribution
- README
- Backend handoff 문서
- CSV schema 문서
- 운영 runbook
- release note
- launcher 구조

---

# 6. v1.0 최종 폴더 구조 예시

```text
Popup Crawler v1.0/
│
├─ Popup Crawler.exe
├─ run_daily.bat
├─ run_daily_scheduled.bat
│
├─ setup_daily_schedule.bat
├─ check_daily_schedule.bat
├─ remove_daily_schedule.bat
│
├─ run_daily.py
├─ run_integrate.py
├─ run_popga.py
├─ run_popply.py
├─ run.py
│
├─ crawlers/
├─ integration/
├─ storage/
├─ config/
├─ tests/
│
├─ launcher/
│  └─ PopupCrawlerLauncher.cs
│
├─ assets/
│  └─ koala_run.ico
│
├─ docs/
│  ├─ BACKEND_HANDOFF.md
│  ├─ CSV_SCHEMA.md
│  ├─ OPERATIONS_RUNBOOK.md
│  └─ RELEASE_NOTES_v1.0.0.md
│
├─ data/
│  ├─ master/
│  ├─ daily/
│  ├─ integration/
│  ├─ popga/
│  ├─ popply/
│  └─ runs/
│
└─ output/
   └─ YYYYMMDD_popup.csv
```

---

# 7. 현재 운영 원칙

## 1. RAW 데이터를 지우지 않는다

사이트 원본 데이터와 정규화 데이터를 분리합니다.

## 2. deterministic rule 우선

Python으로 판단 가능한 것은 LLM에 보내지 않습니다.

## 3. LLM은 마지막 fallback

LLM 호출은 극소수의 애매한 데이터에 한정합니다.

## 4. 크롤러 오류와 source 오류를 구분

사이트 자체 데이터가 잘못된 것인지 parser가 잘못된 것인지 구분합니다.

## 5. 잘못 합치는 것보다 REVIEW가 낫다

중복 여부가 애매하면 자동 merge하지 않습니다.

## 6. 사이트 일시 누락을 종료로 오인하지 않는다

`UNVERIFIED` 상태로 보호합니다.

## 7. 작은 상세 실패는 quarantine

전체 데이터가 정상인데 1~2건이 실패했다고 전체 실행을 버리지 않습니다.

## 8. 이상한 실행 결과는 master에 반영하지 않는다

Safety Gate가 기존 정상 master를 보호합니다.

## 9. Backend는 output CSV를 사용

내부 `data/` 구조와 백엔드 전달 구조를 분리합니다.

---

# 8. 주요 성과

초기에는 단일 사이트의 단순 목록 크롤러였지만, v1.0에서는 아래 수준까지 발전했습니다.

```text
단일 사이트 HTML 파싱
        ↓
3개 source 자동 수집
        ↓
상세정보 검증
        ↓
98% 이상 rule 기반 자동 판정
        ↓
LLM 최소 사용
        ↓
중복 자동 탐지/병합
        ↓
Persistent popup_id
        ↓
Master DB
        ↓
일일 변화 추적
        ↓
Backend CSV
        ↓
자동 스케줄링
        ↓
운영/배포 문서
```

실제 운영 테스트에서 수백 개의 팝업 데이터를 매일 처리하면서도:

```text
classification REVIEW = 0
duplicate REVIEW = 0
```

상태까지 반복적으로 개선했습니다.

---

# 9. 다음 단계 — v1.1 이후

v1.0 이후에는 새로운 크롤링 기능을 무조건 추가하기보다 실제 운영 안정성을 먼저 관찰합니다.

향후 계획:

### Backend Schema Mapping
기존 백엔드 장소 DB 컬럼 구조가 확정되면 현재 CSV exporter를 해당 schema에 맞춥니다.

```text
현재 canonical schema
→ Backend place schema
```

### Server Deployment
Windows PC가 아닌 서버 환경으로 이전할 경우:
- scheduler / cron
- 환경변수 관리
- 로그 수집
- DB ingest
- health check

등을 추가할 수 있습니다.

### Additional Sources
새 source는 단순히 개수를 늘리는 목적이 아니라 기존 3개 source 대비 **고유 신규 팝업 발견률**이 의미 있을 때만 추가합니다.

### Monitoring
- Daily 신규/종료 개수 이상 탐지
- source count 급감
- parser failure
- detail failure
- output CSV missing

등을 운영 모니터링으로 확장할 수 있습니다.

---

# 10. 한 줄 요약

> Popup Crawler v1.0.0은 서울 팝업 데이터를 3개 공개 소스에서 매일 자동 수집하고, 팝업 여부 판정·중복 병합·영구 ID 관리·상태 변화 추적을 수행한 뒤 백엔드가 사용할 수 있는 일일 CSV를 생성하는 내부 운영용 데이터 파이프라인입니다.
