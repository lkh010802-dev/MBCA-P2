# 설치 및 매일 08:00 자동 실행

## A. 처음 설치

1. Python 3 설치 후 명령 프롬프트에서 `python --version` 또는 `py -3 --version` 확인
2. `popup_crawler_v1.0.0.zip` 압축 해제
3. 프로젝트 루트에서 `setup.bat` 실행
4. `.env`를 열어 `OPENAI_API_KEY` 설정
5. 누락 좌표 자동 보완을 위해 `KAKAO_REST_API_KEY` 설정
6. 아래 테스트 실행

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

7. `run_daily.bat`을 한 번 실행하여 `output/YYYYMMDD_popup.csv` 생성 확인

## B. 기존 운영 PC에서 v1.0으로 업그레이드

기존 폴더에 `popup_crawler_v1.0.0_patch.zip`을 덮어쓰는 것을 권장합니다.

보존할 폴더/파일:

```text
data/
output/
logs/
.env
.venv/
```

특히 `data/master/canonical_master.jsonl`은 기존 persistent popup_id와 이력을 유지하는 핵심 파일입니다.

## C. 매일 08:00 자동등록

더블클릭:

```text
setup_daily_schedule.bat
```

- Task name: `PopupCrawlerDaily`
- Schedule: 매일 08:00
- 실행 파일: `run_daily_scheduled.bat`
- 놓친 실행: 가능한 경우 이후 실행
- 절전 해제 요청: 활성화
- 중복 실행: 새 인스턴스 시작 안 함
- 최대 실행시간: 2시간

등록 상태 확인:

```text
check_daily_schedule.bat
```

해제:

```text
remove_daily_schedule.bat
```

다른 시간:

```powershell
.\setup_daily_schedule.bat 06:30
```

같은 Task name으로 다시 등록하면 시간이 갱신됩니다.

## D. 자동실행 로그

```text
logs/scheduler/YYYYMMDD_HHMMSS.log
logs/scheduler/latest.log
```

application-level 결과는 별도로 다음에 저장됩니다.

```text
data/daily/latest_summary.txt
data/daily/latest_report.json
```

## E. PC 상태 제약

현재 자동등록 방식은 현재 Windows 사용자의 `Interactive` logon을 사용합니다.

- PC 켜짐 + 사용자 로그인: 실행 가능
- PC 절전: WakeToRun 요청
- PC 완전 종료: 정시에 실행 불가
- 서버에서 사용자 로그인 없이 24/7 운영: 백엔드팀이 서비스 계정/서버 scheduler 정책에 맞춰 `run_daily.py`를 호출하도록 별도 배치 권장

## F. 프로젝트 폴더를 이동했을 때

Task Scheduler에는 절대 경로가 저장됩니다. 프로젝트 폴더 위치를 변경한 경우:

1. `remove_daily_schedule.bat`
2. 새 위치에서 `setup_daily_schedule.bat`

순서로 다시 등록하십시오.
