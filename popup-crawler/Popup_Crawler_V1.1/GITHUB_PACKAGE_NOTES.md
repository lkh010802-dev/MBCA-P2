# GitHub CLEAN package - 2026-09-04

이 패키지는 현재 운영 중인 v1.0.1 코드에 다음 누적 수정이 포함된 Git 업로드용 소스 패키지입니다.

- 3-source crawler: DayForYou / Popga / Popply
- coordinate enrichment hotfix2
- duplicate review 14건 명시적 판정 반영 (`config/review_decisions.jsonl`)
- operation schedule hotfix5
- 일일 CSV `today_opening_time` / `today_closing_time`
- Popup → Backend common place adapter
- `run_daily.py` 성공 후 backend JSON 자동 생성

제외 항목:

```text
.venv/
.env
data runtime
output runtime
backend_output runtime
logs
__pycache__ / *.pyc
pytest cache
빌드된 Popup Crawler.exe
```

검증: `python -m pytest -q` → 146 passed.
