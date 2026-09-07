# Popup Crawler v1.0.0 Release Notes

## 목적

v0.1~v0.9.7까지 개발/검증한 파이프라인을 내부 운영 및 백엔드 인수인계 가능한 첫 안정 버전으로 동결합니다.

## 포함 기능

- DayForYou / Popga / Popply 3-source fresh crawl
- 상세페이지 enrichment + incremental cache
- deterministic popup/non-popup classifier
- 제한적 LLM fallback (DayForYou ambiguity only)
- cross-source duplicate detection/merge
- provenance 유지
- human review decisions 재사용
- persistent popup_id
- canonical master DB
- ACTIVE / UPCOMING / ENDED / UNVERIFIED lifecycle
- daily change tracking
- source/master safety gates
- Popply quarantine
- `output/YYYYMMDD_popup.csv`
- Windows Task Scheduler 08:00 자동등록/해제/상태확인
- scheduler log
- backend handoff docs

## v1.0 기준 실제 운영 검증

2026-09-01 실제 데이터에서 review 결정을 반영한 최종 통합 예시:

```text
공통 입력 654
POPUP 575 / NON_POPUP 77 / INSUFFICIENT 2
classification_review 0
duplicate_review 0
오늘 Canonical 438
Persistent ID 재사용 434 / 신규 4
Master commit YES
output/20260901_popup.csv 438 rows
```

이 숫자는 고정 기대값이 아니라 해당 시점 snapshot의 검증 기록입니다. 일일 source 데이터에 따라 정상적으로 변합니다.

## 다음 권장 버전

v1.1: 기존 백엔드 장소 DB schema가 확정된 후 CSV/DB mapping 전용 adapter 추가.
