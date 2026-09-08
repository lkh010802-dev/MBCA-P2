# v0.7.1 검증 기록

기준일: 2026-08-31

## Popply 실제 probe

- 전국 공개 렌더링 카드: ACTIVE 140 / UPCOMING 45
- 서울 카드: ACTIVE 117 / UPCOMING 37 / 총 154
- status 불일치: 0
- 상세 probe: 5건 성공 / 0건 실패
- 상세 주소 누락: 0
- 상세 설명 누락: 0
- 목록/상세 이름·시작일·종료일 불일치: 0 / 0 / 0
- 비서울 상세주소: 0
- 저작권 경고 표시: 5 / 5

## probe에서 발견한 source inconsistency

Popply 5864 베리베리는 대표기간이 온라인 판매 시작일인 2026-08-27부터지만,
설명에 실제 `OFFLINE POP-UP` 기간이 2026-09-08~2026-09-17로 명시돼
있었습니다. v0.7.1은 대표기간을 RAW/source header 필드로 보존하고 명시된
오프라인 기간을 canonical 후보 기간으로 사용합니다.

## 기존 실제 파일 회귀검증

- DayForYou 369 + Popga 271 = 640건
- 합의한 검토 결정 적용 후 Canonical preview: 549건
- 분류 검토: 0 / 중복 검토: 0 / LLM: 0
- 이름·주소·시작일 누락 및 역전 날짜: 0

## 부분 3-source 미리보기

- 총 source record: 794
- Popply: POPUP 119 / NON_POPUP 25 / REVIEW 10
- cross-source 분류 전파: 7
- 중복 REVIEW: 1
- Canonical preview: 568
- 다중-source Canonical: 125 (3-source 10)

Popply 149건의 상세주소·설명은 아직 없는 부분 probe이므로 위 통합 수치는
최종값이 아닙니다.

테스트: 35개 통과
