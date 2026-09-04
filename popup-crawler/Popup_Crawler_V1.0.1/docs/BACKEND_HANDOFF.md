# Backend Handoff — Operation Schedule Hotfix4

운영시간 계산은 `operation_schedule`을 기준으로 하십시오.

각 스케줄 객체는 다음 형태입니다.

```json
{
  "days": ["FRI", "SAT", "SUN"],
  "opening_time": "09:00",
  "closing_time": "22:00",
  "closed": false
}
```

휴무는:

```json
{
  "days": ["MON"],
  "opening_time": null,
  "closing_time": null,
  "closed": true
}
```

일일 CSV에는 생성 날짜 기준 편의 필드가 함께 포함됩니다.

- `today_day`
- `today_schedule`
- `today_opening_time`
- `today_closing_time`
- `today_closed`

Backend가 오늘 운영 여부만 확인하는 경우 `today_*`를 바로 사용할 수 있습니다.
사용자가 특정 미래 날짜를 입력하는 추천 요청에서는 `operation_schedule`에서 그 날짜의 요일을 직접 선택하십시오.

요일 코드는 다음으로 통일합니다.

```text
MON TUE WED THU FRI SAT SUN
```

주의: 목요일은 `THR`이 아니라 `THU`입니다.

하루에 여러 운영 세션이 존재하면 `today_opening_time` / `today_closing_time`은 비어 있으며 `today_schedule` 배열을 직접 사용해야 합니다.
