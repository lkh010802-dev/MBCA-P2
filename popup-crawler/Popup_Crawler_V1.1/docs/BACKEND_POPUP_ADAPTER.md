# Popup → Backend Common Place Adapter

## 목적

매일 생성되는 `output/YYYYMMDD_popup.csv`를 기존 Kakao/Tour 장소 normalize 결과와 함께 사용할 수 있는 dict 목록 JSON으로 변환합니다.

## 공통 필드

```python
{
    "source": "popup",
    "source_id": "popup_...",
    "name": "...",
    "latitude": 37.5,
    "longitude": 127.0,
    "category": "shopping",
    "category_detail": "패션",
    "hub_rank": None,
    "address": "서울 ...",
    "distance_m": None,
}
```

`category`는 backend activity enum에 맞춰 deterministic mapping합니다. 원래 crawler category는 `category_detail`에 유지됩니다.

## 운영시간

일일 CSV이므로 backend top-level 시간은 다음과 같이 매핑합니다.

```text
opening_time  <- today_opening_time
closing_time  <- today_closing_time
closed        <- today_closed
```

요일별 전체 정보는 `operation_schedule`에 보존합니다. 시간이 없는 데이터는 추정하지 않고 `null`을 유지합니다.

## 거리

정적 JSON 생성 시 추천 중심 좌표가 없으므로 `distance_m=null`입니다.

백엔드 런타임에서는 crawler CSV를 직접 읽으면서 추천 중심 좌표 기준 거리를 계산할 수 있습니다.

```python
from backend_adapter.popup_backend_adapter import load_popup_places

popup_places = load_popup_places(
    "output/20260904_popup.csv",
    center_latitude=latitude,
    center_longitude=longitude,
    radius_m=2000,
    activities=activities,
)
```

이 결과를 기존 `normalized_kakao_places + filtered_tour_places + normalized_seoul_culture_places`에 더해 공통 ranking 함수로 전달하면 됩니다.
