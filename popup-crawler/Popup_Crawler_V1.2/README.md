# Popup Crawler v1.0.1

서울 팝업스토어 데이터를 **DayForYou + Popga + Popply** 3개 공개 소스에서 수집하고, 팝업/비팝업 판정, 중복 병합, 영구 `popup_id`, 일일 변화 추적, 품질 게이트를 거쳐 백엔드 전달용 CSV를 만드는 운영 버전입니다.

## 1. 최종 산출물

정상 실행이 끝나고 master commit까지 성공한 날에만 다음 파일이 생성됩니다.

```text
output/YYYYMMDD_popup.csv
```

예:

```text
output/20260901_popup.csv
output/20260902_popup.csv
```

CSV는 해당 날짜 기준 **ACTIVE + UPCOMING** 최종 canonical 팝업 snapshot입니다. `ENDED`와 `UNVERIFIED` 이력은 내부 `data/master/`에 보존됩니다.

## 2. 전체 파이프라인

```text
DayForYou fresh crawl + 전체 상세 운영시간 보강 + 필요한 경우만 LLM
                  ┐
Popga list/detail ├─ source별 품질 검증
Popply list/detail┘
        ↓
공통 schema 정규화
        ↓
POPUP / NON_POPUP / INSUFFICIENT 판정
        ↓
source 간 duplicate 후보 생성
        ↓
확실한 중복 자동 병합 + 고정 review decision 적용
        ↓
Canonical popup 생성
        ↓
누락 latitude/longitude 보완
(cache → 동일주소 재사용 → Kakao 주소검색 → 키워드 fallback)
        ↓
기존 master와 persistent popup_id 매칭
        ↓
ACTIVE / UPCOMING / ENDED / UNVERIFIED
        ↓
일일 변화 추적
        ↓
품질 gate 통과 + master commit
        ↓
output/YYYYMMDD_popup.csv
```

## 3. 신규 PC/백엔드 환경 설치

Windows 기준:

1. Python 설치
2. 이 ZIP 압축 해제
3. `setup.bat` 실행
4. 생성된 `.env`에 `OPENAI_API_KEY` 입력
5. 좌표 자동 보완을 위해 `.env`에 `KAKAO_REST_API_KEY` 입력
6. 테스트 실행

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

7. `run_daily.bat`을 한 번 수동 실행하여 정상 CSV 생성 확인

> 기존 운영 PC에서 백엔드 서버로 이전하면서 **기존 popup_id와 이력까지 유지**하려면 현재 운영 폴더의 `data/master/`를 새 환경으로 함께 복사하십시오. 필요하면 `data/popga/runs/`, `data/popply/runs/`도 옮기면 상세 캐시를 이어서 사용할 수 있어 첫 실행이 빨라집니다.

## 4. 매일 오전 8시 자동 실행

수동 설정 없이 다음 파일을 더블클릭하면 됩니다.

```text
setup_daily_schedule.bat
```

기본값은 매일 **08:00**입니다. UAC 확인 창이 한 번 뜰 수 있습니다.

등록 확인:

```text
check_daily_schedule.bat
```

자동 실행 해제:

```text
remove_daily_schedule.bat
```

다른 시간으로 등록하려면 PowerShell/명령 프롬프트에서 예를 들어:

```powershell
.\setup_daily_schedule.bat 07:30
```

자동 실행은 `run_daily_scheduled.bat`을 사용하므로 `pause` 없이 종료되며 로그는 다음에 남습니다.

```text
logs/scheduler/YYYYMMDD_HHMMSS.log
logs/scheduler/latest.log
```

현재 Windows 자동등록은 보안상 **현재 사용자가 로그인한 상태에서 실행**하는 방식입니다. 절전 상태에서는 WakeToRun을 요청하며, PC가 완전히 꺼져 있으면 실행되지 않습니다. 놓친 시간은 Windows의 StartWhenAvailable 설정에 따라 로그인/가동 후 실행될 수 있습니다.

## 5. 운영 명령

사람이 직접 실행:

```text
run_daily.bat
```

무인/Task Scheduler 실행:

```text
run_daily_scheduled.bat
```

최신 source 결과만 재통합하며 master를 건드리지 않는 점검:

```powershell
.\.venv\Scripts\python.exe run_daily.py --reuse-latest --no-commit
```

## 6. 안전 정책

다음과 같은 경우 master와 backend CSV를 갱신하지 않습니다.

- source 단계 자체 실패
- source 데이터가 이전 정상 실행 대비 비정상 급락
- 상세 실패율이 허용치를 초과
- Popply 상태 필터 갱신 이상
- classification REVIEW 잔여
- duplicate REVIEW 잔여
- canonical 결과가 0건

Popply 상세 실패가 아주 적은 경우(기본 `2건 이하 AND 2% 이하`)에는 문제 레코드만 quarantine하고 정상 레코드는 계속 처리합니다.


## 6-1. 누락 좌표 자동 보완

통합된 Canonical에 유효한 서울 좌표가 없을 때만 다음 순서로 보완합니다. 기존 source 좌표는 덮어쓰지 않습니다.

```text
영구 geocode cache
→ 동일 address_base의 신뢰 가능한 기존 좌표 재사용
→ Kakao 주소 검색(address_base)
→ Kakao 키워드 장소 검색(venue/address/name)
→ 실패 시 unresolved로 남김
```

감사 파일:

```text
data/integration/runs/<timestamp>/geocode_report.json
data/integration/runs/<timestamp>/geocode_unresolved.jsonl
data/cache/kakao_geocode_cache.json
```

`KAKAO_REST_API_KEY`가 없더라도 캐시/동일주소 재사용은 수행하며, Kakao API 단계만 건너뜁니다. 임시로 전체 좌표 보완을 끄려면 `run_integrate.py --no-geocode`를 사용할 수 있습니다.

이미 만들어진 CSV만 다시 보완할 수도 있습니다. 원본은 보존하고 기본적으로 `_geocoded.csv`를 새로 만듭니다.

```powershell
.\.venv\Scripts\python.exe backfill_coordinates.py output/20260902_popup.csv
```

API 없이 동일주소/캐시만 적용하려면:

```powershell
.\.venv\Scripts\python.exe backfill_coordinates.py output/20260902_popup.csv --no-api
```


## 6-2. 운영시간 보강 / 백엔드 구조화

DayForYou는 목록 페이지가 아니라 상세페이지에 운영시간을 제공하는 경우가 많습니다. v1.0.1부터는 LLM 검토 대상뿐 아니라 **서울 후보 전체의 상세페이지를 재파싱**하여 운영시간을 수집합니다.

```text
DayForYou 상세페이지
→ 운영시간 원문 보존
→ canonical operation_hours 선택
→ operation_schedule 구조화
→ 단일 공통시간이면 opening_time / closing_time 생성
```

백엔드 CSV에는 기존 `operation_hours`를 유지하면서 다음 컬럼을 제공합니다.

```text
operation_hours_raw
operation_schedule
today_day
today_schedule
today_opening_time
today_closing_time
today_closed
```

요일별 전체 정보는 `operation_schedule`에 보존하고, 매일 생성되는 CSV에서는 해당 날짜의 실제 영업시간을 `today_opening_time` / `today_closing_time`으로 별도 제공합니다. 원문과 구조화 결과를 분리하여 parser 오해석이 생겨도 원천 증거를 보존합니다.

DayForYou 상세 운영시간 미확보 항목은 각 run의 다음 파일에서 확인할 수 있습니다.

```text
data/runs/<timestamp>/operation_hours_missing_details.jsonl
```

## 7. 폴더 역할

```text
data/                  내부 운영 데이터/감사/히스토리
  master/              영구 canonical master
  daily/               일일 실행 보고서
  integration/runs/    통합 결과 감사 데이터
  popga/runs/           Popga 원천/상세 결과
  popply/runs/          Popply 원천/상세 결과
  runs/                 DayForYou 결과

output/                 백엔드 전달용 원본 일일 CSV
backend_output/         Kakao/Tour 공통 dict 형태로 변환된 일일 JSON
logs/scheduler/         Windows 자동실행 wrapper 로그
config/                 사람 검토로 고정한 판정
```

## 8. 백엔드 인수인계

`run_daily.py`가 성공하면 `output/YYYYMMDD_popup.csv`를 만든 뒤 자동으로 다음 백엔드용 JSON도 생성합니다.

```text
backend_output/YYYYMMDD_popup_places.json
backend_output/latest_popup_places.json
```

JSON의 공통 필드는 기존 Kakao/Tour normalize 결과와 같은 `source`, `source_id`, `name`, `latitude`, `longitude`, `category`, `category_detail`, `hub_rank`, `address`, `distance_m` 구조를 사용합니다. 팝업의 `opening_time` / `closing_time`은 일일 CSV의 `today_opening_time` / `today_closing_time`을 사용합니다. 정적 파일의 `distance_m`은 추천 기준 좌표가 아직 없으므로 `null`이며, `backend_adapter.load_popup_places()`에 기준 좌표를 넘기면 런타임 계산할 수 있습니다.

자세한 내용:

- [백엔드 인수인계](docs/BACKEND_HANDOFF.md)
- [CSV 스키마](docs/CSV_SCHEMA.md)
- [운영/장애 대응](docs/OPERATIONS_RUNBOOK.md)
- [설치 및 자동실행](docs/INSTALL_AND_SCHEDULE.md)
- [v1.0 릴리스 노트](docs/RELEASE_NOTES_v1.0.0.md)

## 9. 현재 운영 기준

v1.0.1은 v1.0.0 운영 기준에 운영시간 보강/구조화와 엄격한 동일-source 중복 보정을 추가한 버전입니다. 기존 v1.0.0은 2026-09-01 실제 일일 전환에서 다음 구조를 검증한 v0.9.7을 운영 버전으로 묶은 것입니다.

- 3-source fresh crawl
- 상세 캐시/재검증
- 분류 및 중복 REVIEW 0까지 수동 결정 반영
- persistent `popup_id`
- master history/lifecycle
- daily changes
- backend CSV snapshot
- source/master safety gate

이 버전부터는 기능을 무작정 추가하기보다 실제 며칠간 일일 실행 안정성을 관찰한 뒤 백엔드 스키마 매핑을 v1.1에서 진행하는 것을 권장합니다.
