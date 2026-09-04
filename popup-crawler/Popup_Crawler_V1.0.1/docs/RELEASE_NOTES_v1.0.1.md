# Popup Crawler v1.0.1 Release Notes

기준일: 2026-09-04

## 핵심 수정

1. DayForYou 운영시간 상세 수집 누락 수정
2. 운영시간 원문/요일별 구조/단순 시작·종료시간 분리
3. 운영시간 coverage audit 추가
4. 동일 source의 완전 동일 upstream event 중복 병합
5. v1.0.0 coordinate hotfix2 유지

## 대표 검증

DayForYou 상세 DOM의 다음 패턴을 테스트했습니다.

- `시간 : 10:30~22:00`
- `평일 10:30~20:00, 금~일/공휴일 10:30~20:30`
- `월-목 10:30-20:00 / 금-일 10:30-20:30`
- `매주 금/토/일 (주간) 11:00~18:00, (야간)16:00~22:00`
- `월-금 : 10:00-17:50 / 하루 총 5회 관람`

전체 자동 테스트 115개 통과.

## Regression validation

- DayForYou simple schedule form `시간 : 10:30~22:00` is parsed into raw + structured fields.
- `[오베르캄프] 사워도우 에그타르트` duplicate source IDs `30071` / `28671` are covered by the same-source exact-identity regression tests after street-level address normalization.
- Full suite: 115 tests passed.
