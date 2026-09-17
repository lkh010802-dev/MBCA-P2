import run  # noqa: F401  # extension-first import path를 실제 실행과 동일하게 구성

from conditions import (
    allows_mountain_activity,
    extract_explicit_activity_location,
    extract_explicit_current_location,
    extract_explicit_end_location,
    infer_activity_sequence,
    requests_nearby,
)


def test_meal_then_rest_adds_cafe_after_food():
    assert infer_activity_sequence("신림역에서 밥 먹고 쉬고 싶어", ["food"]) == [
        "food",
        "cafe",
    ]


def test_exhibition_request_removes_unmentioned_food_and_cafe():
    assert infer_activity_sequence(
        "오늘은 3시간 동안 전시회를 보고 싶어",
        ["food", "cafe", "culture"],
    ) == ["culture"]


def test_exhibition_keeps_explicit_cafe_as_secondary_activity():
    assert infer_activity_sequence(
        "전시 보고 카페에서 쉬고 싶어",
        ["food", "culture"],
    ) == ["culture", "cafe"]


def test_cafe_then_exhibition_keeps_user_order():
    assert infer_activity_sequence(
        "친구랑 카페 갔다가 전시 보고 싶어",
        ["culture", "cafe"],
    ) == ["cafe", "culture"]


def test_start_activity_area_and_next_schedule_are_separate():
    message = "지금 대림역인데 8시까지 신림역 가기 전에 어디 들를까?"
    assert extract_explicit_current_location(message) == "대림역"
    assert extract_explicit_activity_location(message) is None
    assert extract_explicit_end_location(message) == "신림역"


def test_activity_area_is_detected_independently_from_gps():
    assert (
        extract_explicit_activity_location("신림역에서 밥 먹고 카페에서 쉬고 싶어")
        == "신림역"
    )


def test_nearby_and_mountain_require_explicit_language():
    assert requests_nearby("이 주변에서 잠깐 쉬고 싶어") is True
    assert allows_mountain_activity("신림 가기 전에 어디 들를까?", []) is False
    assert allows_mountain_activity("관악산 등산하고 싶어", ["walk"]) is True
