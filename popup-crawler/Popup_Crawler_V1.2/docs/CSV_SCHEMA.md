# Backend CSV Schema — Operation Schedule Hotfix4

Backend용 일일 CSV는 ACTIVE/UPCOMING 팝업만 포함하며 UTF-8 BOM으로 저장됩니다.

운영시간 관련 핵심 필드:

| 필드 | 의미 | 형식 |
|---|---|---|
| operation_hours | 선택된 원천 운영시간 | JSON array 문자열 |
| operation_hours_raw | 원문 보존 | JSON array 문자열 |
| operation_schedule | 요일별 구조화 운영시간. 운영시간의 기준 데이터 | JSON array 문자열 |
| today_day | CSV 생성 날짜의 요일 | MON~SUN |
| today_schedule | 해당 요일에 적용되는 스케줄만 추린 값 | JSON array 문자열 |
| today_opening_time | 오늘 단일 운영구간의 시작시간 | HH:MM 또는 빈값 |
| today_closing_time | 오늘 단일 운영구간의 종료시간 | HH:MM 또는 빈값 |
| today_closed | 오늘 명시적 휴무 여부 | true / false / 빈값 |

## operation_schedule

```json
[
  {
    "days": ["MON", "TUE", "WED", "THU"],
    "opening_time": "12:00",
    "closing_time": "19:00",
    "closed": false
  },
  {
    "days": ["FRI", "SAT", "SUN"],
    "opening_time": "09:00",
    "closing_time": "22:00",
    "closed": false
  }
]
```

요일별 시간이 다르더라도 전역 대표시간을 만들지 않습니다.
Backend가 임의로 `09:00~22:00`을 월요일에도 적용하면 안 됩니다.

## CSV 생성일 기준 선택

2026-09-04(FRI)라면:

```text
today_day=FRI
today_opening_time=09:00
today_closing_time=22:00
today_closed=false
```

월요일이라면 같은 팝업이:

```text
today_day=MON
today_opening_time=12:00
today_closing_time=19:00
today_closed=false
```

으로 출력됩니다.

## 분리 세션

```json
[
  {"days":["FRI"],"opening_time":"11:00","closing_time":"14:00","closed":false},
  {"days":["FRI"],"opening_time":"17:00","closing_time":"22:00","closed":false}
]
```

이 경우 `today_schedule`은 두 세션을 모두 포함하지만 `today_opening_time` / `today_closing_time`은 빈값입니다.
백엔드는 `today_schedule`의 각 세션을 별도 구간으로 계산해야 합니다.

## 휴무 / 미확인

명시적 휴무:

```json
{"days":["MON"],"opening_time":null,"closing_time":null,"closed":true}
```

- 휴무가 명시되면 `today_closed=true`
- 영업구간이 있으면 `today_closed=false`
- 해당 요일 정보 자체가 없거나 서로 충돌하면 `today_closed`는 빈값

## 주의

`operation_schedule`이 Source of Truth입니다.
`today_*` 필드는 일일 CSV를 빠르게 조회하기 위한 편의 필드입니다.
사용자가 미래 날짜를 요청하는 추천 기능에서는 Backend가 `operation_schedule`에서 요청 날짜의 요일을 직접 선택하는 것을 권장합니다.
