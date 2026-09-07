from __future__ import annotations

import csv
import json
from pathlib import Path

from backend_adapter.popup_backend_adapter import (
    infer_backend_category,
    load_popup_places,
    normalize_popup_row,
)


def base_row(**overrides):
    row = {
        "popup_id": "popup_test",
        "name": "테스트 패션 팝업",
        "category": "패션",
        "categories": '["패션"]',
        "latitude": "37.5",
        "longitude": "127.0",
        "address": "서울 테스트구 테스트로 1",
        "today_opening_time": "10:30",
        "today_closing_time": "20:30",
        "today_closed": "false",
        "operation_schedule": '[{"days":["FRI"],"opening_time":"10:30","closing_time":"20:30","closed":false}]',
        "tags": '["#패션"]',
        "confidence": "0.9",
    }
    row.update(overrides)
    return row


def test_today_hours_become_backend_open_close():
    place = normalize_popup_row(base_row())
    assert place is not None
    assert place["source"] == "popup"
    assert place["source_id"] == "popup_test"
    assert place["opening_time"] == "10:30"
    assert place["closing_time"] == "20:30"
    assert place["closed"] is False
    assert place["category"] == "shopping"


def test_missing_today_hours_stay_null():
    place = normalize_popup_row(base_row(today_opening_time="", today_closing_time="", today_closed=""))
    assert place is not None
    assert place["opening_time"] is None
    assert place["closing_time"] is None
    assert place["closed"] is None


def test_simple_category_mapping():
    assert infer_backend_category(base_row(category="F&B")) == "food"
    assert infer_backend_category(base_row(category="애니/캐릭터")) == "entertainment"
    assert infer_backend_category(base_row(category="콘텐츠/문화")) == "culture"
    assert infer_backend_category(base_row(category="", name="성수 콜라보 카페 팝업")) == "cafe"


def test_runtime_distance_and_radius_filter(tmp_path: Path):
    path = tmp_path / "popup.csv"
    fields = list(base_row().keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(base_row())
    places = load_popup_places(
        path,
        center_latitude=37.5,
        center_longitude=127.0,
        radius_m=100,
    )
    assert len(places) == 1
    assert places[0]["distance_m"] == 0
