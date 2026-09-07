# Popup Crawler v1.0.1 CLEAN — 처음부터 다시 시작

이 폴더는 기존 `coordinate`, `hotfix2`, `.venv`, `.env`, `data/master`, cache, output을 이어받지 않는 **완전 새 시작용** 패키지입니다.

## 1. 압축 해제

예시:

```text
C:\Users\mbc\Downloads\popup_crawler_v1.0.1_CLEAN\
```

폴더 안에 `setup.bat`, `run_daily.bat`, `run_daily_scheduled.bat`가 바로 보여야 합니다.

## 2. 최초 1회 설치

`setup.bat` 더블클릭

자동으로:
- `.venv` 생성
- requirements 설치
- Playwright Chromium 설치
- `.env.example` → `.env` 생성
- `output/`, `logs/scheduler/` 생성

## 3. .env 설정

생성된 `.env`에 최소 다음 값을 입력합니다.

```text
OPENAI_API_KEY=...
KAKAO_REST_API_KEY=...
```

기존 폴더의 `.env` 값을 복사해도 되지만, `.venv`, `data`, `output`, cache 파일은 복사하지 않는 것을 권장합니다.

## 4. 최초 수동 실행

`run_daily.bat` 더블클릭

정상 완료 후 확인:

```text
data\daily\latest_report.json
output\YYYYMMDD_popup.csv
```

※ 중복 REVIEW 등 Quality Gate가 발생하면 CSV가 생성되지 않을 수 있으며, 이는 안전장치의 정상 동작입니다.

## 5. n8n 경로 변경

기존 n8n Workflow의 `Run Popup Crawler` Execute Command를 새 폴더 경로로 변경합니다.

```bat
cd /d "C:\Users\mbc\Downloads\popup_crawler_v1.0.1_CLEAN" && call "run_daily_scheduled.bat"
```

`Read Daily Report`도 새 경로로 변경:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Raw -Encoding UTF8 'C:\Users\mbc\Downloads\popup_crawler_v1.0.1_CLEAN\data\daily\latest_report.json'"
```

`Verify Backend CSV`도 새 폴더의 `output`을 바라보도록 변경합니다.

## 6. 기존 폴더는 바로 삭제하지 않기

새 CLEAN 폴더가 1~2회 정상 실행되는 것을 확인한 뒤 기존 `coordinate`, `hotfix2` 폴더를 정리하세요.

---

## 이번 버전 주요 기능

- DayForYou / Popga / Popply 수집
- DayForYou 전체 상세 운영시간 보강
- `operation_hours_raw`
- `operation_schedule`
- `opening_time`
- `closing_time`
- Kakao 좌표 보완
- 중복 병합 / Persistent popup_id
- Master Safety Gate
- Backend CSV 생성
