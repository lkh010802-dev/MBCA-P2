import json
import sys

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR / "core"))
sys.path.insert(0, str(BACKEND_DIR / "extensions"))

from popup_data_selector import (
    filter_recommendable_popup_places,
    get_popup_data_candidates,
    is_sales_centered_without_experience,
    load_popup_places_for_date,
)
from models import PlaceRecommendRequest
from place_routes import recommend_actual_places
from proactive_recommendation_service import find_proactive_suggestion


KST = timezone(timedelta(hours=9))


def _popup(name):
    return {
        "source_id": name,
        "name": name,
        "latitude": 37.55,
        "longitude": 126.98,
        "category": "culture",
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "operation_schedule": [],
    }


def _write_popup_file(directory, filename, name):
    path = directory / filename
    path.write_text(
        json.dumps([_popup(name)], ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_candidates_prioritize_reference_date_then_kst_today_then_latest(tmp_path):
    _write_popup_file(tmp_path, "20260919_popup_places.json", "이전")
    _write_popup_file(tmp_path, "20260921_popup_places.json", "오늘")
    _write_popup_file(tmp_path, "20260920_popup_places.json", "최신 fallback")

    candidates = get_popup_data_candidates(
        date(2026, 9, 18),
        now=datetime(2026, 9, 21, 9, tzinfo=KST),
        data_dir=tmp_path,
    )

    assert [path.name for path in candidates] == [
        "20260918_popup_places.json",
        "20260921_popup_places.json",
        "20260920_popup_places.json",
        "20260919_popup_places.json",
    ]


def test_loader_uses_requested_date_when_available(tmp_path, caplog):
    _write_popup_file(tmp_path, "20260920_popup_places.json", "요청일 팝업")
    _write_popup_file(tmp_path, "20260921_popup_places.json", "오늘 팝업")

    with caplog.at_level("INFO", logger="uvicorn.error"):
        places = load_popup_places_for_date(
            date(2026, 9, 20),
            now=datetime(2026, 9, 21, 9, tzinfo=KST),
            data_dir=tmp_path,
        )

    assert places[0]["name"] == "요청일 팝업"
    assert "date=2026-09-20" in caplog.text
    assert "file=20260920_popup_places.json" in caplog.text


def test_loader_falls_back_to_today_then_latest_valid_file(tmp_path):
    _write_popup_file(tmp_path, "20260919_popup_places.json", "최신 정상 팝업")
    (tmp_path / "20260921_popup_places.json").write_text(
        "not-json",
        encoding="utf-8",
    )

    places = load_popup_places_for_date(
        date(2026, 9, 20),
        now=datetime(2026, 9, 21, 9, tzinfo=KST),
        data_dir=tmp_path,
    )

    assert places[0]["name"] == "최신 정상 팝업"


def test_loader_returns_empty_without_raising_when_no_data_exists(tmp_path):
    places = load_popup_places_for_date(
        date(2026, 9, 20),
        now=datetime(2026, 9, 21, 9, tzinfo=KST),
        data_dir=tmp_path,
    )

    assert places == []


def test_sales_focused_gift_popups_are_not_recommendable():
    gift_popups = [
        {
            "name": "[신지어부가] 전복 선물세트 Pop-Up",
            "description": "완도 수산물로 만든 건강한 한 끼",
            "tags": ["#전복선물세트Pop-Up"],
        },
        {
            "name": "[스톤헨지] 추석 Gift Pop-Up",
            "description": "행사상품 35~60% OFF 및 단독 특가 안내",
            "tags": ["#추석GiftPop-Up"],
        },
    ]

    assert all(
        is_sales_centered_without_experience(place)
        for place in gift_popups
    )
    assert filter_recommendable_popup_places(gift_popups) == []


def test_discount_popup_with_an_experience_is_kept():
    popup = {
        "name": "향수 브랜드 팝업",
        "description": (
            "오픈 기념 20% 할인과 함께 향을 직접 시향하고 "
            "나만의 향을 만드는 체험을 제공합니다."
        ),
    }

    assert not is_sales_centered_without_experience(popup)
    assert filter_recommendable_popup_places([popup]) == [popup]


def test_limited_goods_popup_is_kept_despite_purchase_benefits():
    popup = {
        "name": "캐릭터 콜라보 팝업",
        "description": (
            "팝업 한정 굿즈와 신제품을 공개하며 "
            "5만원 이상 구매 시 포토카드를 증정합니다."
        ),
    }

    assert not is_sales_centered_without_experience(popup)


def test_benefit_only_card_notice_is_filtered():
    popup = {
        "name": "NH농협 / 우리카드 최대 6개월 무이자 할부",
        "description": "type=gift",
    }

    assert is_sales_centered_without_experience(popup)


def test_loader_logs_and_filters_sales_only_popups(tmp_path, caplog):
    path = tmp_path / "20260921_popup_places.json"
    path.write_text(
        json.dumps(
            [
                {
                    **_popup("체험 팝업"),
                    "description": "현장에서 직접 시향할 수 있습니다.",
                },
                {
                    **_popup("추석 Gift Pop-Up"),
                    "description": "행사상품 35~60% OFF",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with caplog.at_level("INFO", logger="uvicorn.error"):
        places = load_popup_places_for_date(
            now=datetime(2026, 9, 21, 9, tzinfo=KST),
            data_dir=tmp_path,
        )

    assert [place["name"] for place in places] == ["체험 팝업"]
    assert "count=1" in caplog.text
    assert "excluded_sales=1" in caplog.text
    assert "raw_count=2" in caplog.text


def test_place_request_forwards_reference_date_to_recommendation_service():
    received = {}
    request = PlaceRecommendRequest(
        area_name="성수",
        latitude=37.54,
        longitude=127.05,
        activities=["culture"],
        reference_date="2026-09-20",
    )

    def recommend_places_fn(**kwargs):
        received.update(kwargs)
        return []

    def create_page_fn(**kwargs):
        return SimpleNamespace(
            area_name=kwargs["area_name"],
            places=[],
            cursor=None,
            has_more=False,
            next_offset=None,
        )

    recommend_actual_places(
        request,
        recommend_places_fn,
        create_page_fn,
    )

    assert received["reference_date"] == date(2026, 9, 20)


def test_proactive_recommendation_uses_departure_date_as_reference_date():
    received = {}

    def load_popup_places_fn(**kwargs):
        received.update(kwargs)
        return []

    result = find_proactive_suggestion(
        start_location={"x": 127.05, "y": 37.54},
        departure_datetime=datetime(2026, 9, 20, 10, tzinfo=KST),
        end_location=None,
        end_datetime=None,
        transport_mode="walk",
        load_popup_places_fn=load_popup_places_fn,
        load_culture_places_fn=lambda **kwargs: [],
    )

    assert result is None
    assert received["reference_date"] == date(2026, 9, 20)
