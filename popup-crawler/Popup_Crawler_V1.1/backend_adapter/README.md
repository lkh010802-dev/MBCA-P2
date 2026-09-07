# Popup Backend Adapter

매일 생성되는 `output/YYYYMMDD_popup.csv`를 백엔드 공통 장소 dict 형식의 JSON으로 변환합니다.

## 자동 출력

`run_daily.py`가 성공적으로 master commit + CSV 생성을 끝내면 자동으로 다음 파일을 만듭니다.

```text
backend_output/YYYYMMDD_popup_places.json
backend_output/latest_popup_places.json
backend_output/latest_export_report.json
```

`opening_time` / `closing_time`은 일일 CSV의 `today_opening_time` / `today_closing_time`을 그대로 사용합니다.
요일별 전체 시간은 `operation_schedule`에 계속 보존됩니다.

## 백엔드 공통 필드

```text
source
source_id
name
latitude
longitude
category
category_detail
hub_rank
address
distance_m
```

팝업 전용 확장 필드:

```text
start_date / end_date / status / venue_name
opening_time / closing_time / closed
operation_schedule
description / image_url / detail_url / official_url / reservation_url
popup_categories / tags / confidence
```

정적 일일 JSON을 만들 때 `distance_m`은 `null`입니다. 추천 요청의 기준 좌표마다 거리가 달라지기 때문입니다.
백엔드에서는 `load_popup_places(..., center_latitude=..., center_longitude=..., radius_m=...)`를 사용하면 런타임 거리 계산이 가능합니다.

## 수동 실행

```powershell
.\.venv\Scripts\python.exe run_backend_export.py
```

특정 CSV 지정:

```powershell
.\.venv\Scripts\python.exe run_backend_export.py --input output\20260904_popup.csv
```
