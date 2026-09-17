"""Regression tests for the integrated extension time contract."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from run import app  # noqa: F401 - activates extension-first imports
from course_time_evaluator import evaluate_course_time
from route_leg_builder import build_travel_legs
from route_travel_time import calculate_route_travel_times


START = {"latitude": 37.49, "longitude": 126.89}
PLACE = {"activity": "cafe", "category": "cafe", "latitude": 37.48, "longitude": 126.91}
END = {"latitude": 37.48, "longitude": 126.93}


def test_final_destination_creates_and_counts_the_last_leg():
    legs = build_travel_legs(START, [PLACE], END)
    assert len(legs) == 2
    assert legs[-1]["destination"] == END

    with (
        patch("course_time_evaluator.validate_selected_places_stay_time", return_value={"total_stay_duration_minutes": 60}),
        patch("course_time_evaluator.calculate_route_travel_times", return_value={"legs": [{"travel_time_minutes": 10}, {"travel_time_minutes": 20}], "total_travel_time_minutes": 30}),
    ):
        result = evaluate_course_time(START, [PLACE], 90, END, "public_transit")

    assert result["total_stay_time_minutes"] == 60
    assert result["total_travel_time_minutes"] == 30
    assert result["total_required_minutes"] == 90
    assert result["remaining_time_minutes"] == 0
    assert result["status"] == "FEASIBLE"


def test_api_preserves_budget_transport_and_final_leg_contract():
    captured = {}

    def optimizer(**kwargs):
        captured.update(kwargs)
        return {
            "optimized_places": kwargs["selected_places"],
            "legs": [{"travel_time_minutes": 10}, {"travel_time_minutes": 20}],
            "total_stay_time_minutes": 60,
            "total_travel_time_minutes": 30,
            "total_required_minutes": 90,
            "available_time_minutes": kwargs["available_time_minutes"],
            "remaining_time_minutes": kwargs["available_time_minutes"] - 90,
            "status": "FEASIBLE",
        }

    body = {
        "start_location": START,
        "selected_places": [{"category": "cafe", "latitude": PLACE["latitude"], "longitude": PLACE["longitude"], "specified_duration_minutes": 60}],
        "available_time_minutes": 180,
        "optimize_order": True,
        "end_location": END,
        "transport_mode": "car",
    }
    with patch("course_routes.optimize_course_order", side_effect=optimizer):
        response = TestClient(app).post("/recommend/course", json=body)

    assert response.status_code == 200
    assert captured["available_time_minutes"] == 180
    assert captured["transport_mode"] == "car"
    assert captured["end_location"] == END
    assert response.json()["available_time_minutes"] == 180


def test_one_minute_over_budget_is_infeasible():
    with (
        patch("course_time_evaluator.validate_selected_places_stay_time", return_value={"total_stay_duration_minutes": 60}),
        patch("course_time_evaluator.calculate_route_travel_times", return_value={"legs": [{"travel_time_minutes": 31}], "total_travel_time_minutes": 31}),
    ):
        result = evaluate_course_time(START, [PLACE], 90, None, "walk")

    assert result["total_required_minutes"] == 91
    assert result["remaining_time_minutes"] == -1
    assert result["status"] == "INFEASIBLE"


@pytest.mark.parametrize("bad_travel", [None, {"mode": "walk"}, {"duration_min": None}, {"duration_min": -1}])
def test_unavailable_duration_is_never_converted_to_zero(bad_travel):
    leg = {"origin": START, "destination": PLACE}
    with patch("route_travel_time.get_travel", return_value=bad_travel):
        with pytest.raises(RuntimeError, match="이동시간"):
            calculate_route_travel_times([leg], "walk")


def test_zero_minutes_is_allowed_only_for_the_same_location():
    same_leg = {"origin": START, "destination": START.copy()}
    with patch("route_travel_time.get_travel", return_value={"duration_min": 0, "mode": "walk"}):
        result = calculate_route_travel_times([same_leg], "walk")
    assert result["total_travel_time_minutes"] == 0

    different_leg = {"origin": START, "destination": PLACE}
    with patch("route_travel_time.get_travel", return_value={"duration_min": 0, "mode": "walk"}):
        with pytest.raises(RuntimeError, match="유효한 이동시간"):
            calculate_route_travel_times([different_leg], "walk")
