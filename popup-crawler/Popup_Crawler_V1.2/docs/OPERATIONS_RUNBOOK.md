# 운영 / 장애 대응 Runbook

## 1. 정상 실행

```text
status: SUCCESS
classification_review=0
duplicate_review=0
master_committed=True
output/YYYYMMDD_popup.csv 생성
```

## 2. BLOCKED는 데이터 보호 동작

`BLOCKED_*`는 크롤러가 무조건 실패했다는 뜻보다 **의심스러운 결과로 master/CSV를 덮어쓰지 않았다는 뜻**입니다.

우선 확인:

```text
data/daily/latest_summary.txt
data/daily/latest_report.json
logs/scheduler/latest.log
```

## 3. BLOCKED_SOURCE_STAGE

원인 예:

- DNS/인터넷 문제
- 사이트 접속 실패
- Playwright 실행 실패

대응:

1. 인터넷/사이트 접근 확인
2. 수동 `run_daily.bat` 재실행
3. 반복되면 해당 source report/trace 확인

## 4. BLOCKED_SOURCE_QUALITY

원인 예:

- 후보 수 비정상 급락
- 상세 실패율 과다
- Popply 상태 필터 갱신 이상
- Popply core detail 불완전 다수

작은 Popply detail 실패는 quarantine됩니다.

```text
data/popply/runs/<timestamp>/detail_quarantine.jsonl
```

허용량 초과 시 전체 commit을 차단합니다.

## 5. BLOCKED_INTEGRATION

주요 원인:

```text
classification_review > 0
duplicate_review > 0
```

확인 파일:

```text
data/integration/runs/<timestamp>/classification_review.jsonl
data/integration/runs/<timestamp>/duplicate_review.jsonl
```

판정 후 `config/review_decisions.jsonl`에 명시적 결정을 추가하고 최신 source를 다시 통합할 수 있습니다.

## 6. Master 강제 commit 금지 원칙

운영 기본값에서는 REVIEW가 남은 상태로 `--allow-review-commit`을 사용하지 마십시오. 이 옵션은 개발/복구 목적이며 일반 운영에서는 사용하지 않습니다.

## 7. CSV가 생성되지 않았을 때

정상 정책입니다. CSV는 master commit 성공 후에만 생성합니다.

```text
BLOCKED/FAILED
→ 기존 master 보호
→ 해당 날짜 CSV 미갱신
```

## 8. 같은 날 여러 번 실행

같은 날짜 파일명은 최신 성공 snapshot으로 덮어씁니다.

```text
output/20260901_popup.csv
```

persistent ID 기준 변화 추적이므로 동일 snapshot 재실행은 신규/종료가 중복 집계되지 않아야 합니다.

## 9. 일일 변화 확인

```text
data/daily/latest_changes.json
```

주요 항목:

- new
- ended
- reappeared
- changed
- unverified
- source_changes
- retired

월말→월초에는 `end_date`가 전월 말일인 팝업들이 다수 ENDED로 전환될 수 있습니다.
