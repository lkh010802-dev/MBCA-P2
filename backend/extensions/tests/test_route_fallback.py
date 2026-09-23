from unittest.mock import Mock, patch

import map_service
import route_travel_time


def test_walking_uses_nonzero_estimate_when_tmap_is_unavailable():
    with patch.object(map_service, "get_tmap_walking", return_value=None):
        route = map_service.get_walking(126.93, 37.48, 126.94, 37.49)

    assert route["duration_min"] > 0
    assert route["calculation_status"] == "estimated"
    assert route["source"] == "distance_fallback"


def test_walking_prefers_tmap_duration_when_available():
    tmap_route = {
        "duration_min": 11,
        "distance_m": 730,
        "paths": [{"type": "WALKING", "points": [[126.93, 37.48], [126.94, 37.49]]}],
        "instructions": [],
    }
    with patch.object(map_service, "get_tmap_walking", return_value=tmap_route):
        route = map_service.get_walking(126.93, 37.48, 126.94, 37.49)

    assert route["duration_min"] == 11
    assert route["calculation_status"] == "exact"
    assert route["source"] == "tmap_pedestrian"


def test_nearby_transit_failure_falls_back_to_walking():
    with (
        patch.object(map_service, "get_transit", return_value=None),
        patch.object(
            map_service,
            "get_walking",
            return_value={
                "mode": "walk",
                "duration_min": 18,
                "paths": [],
                "calculation_status": "estimated",
            },
        ),
    ):
        route = map_service.get_travel(
            126.93,
            37.48,
            126.94,
            37.49,
            transport_mode="public_transit",
        )

    assert route["duration_min"] == 18
    assert route["fallback_from"] == "public_transit"
    assert route["calculation_status"] == "estimated"


def test_route_result_counts_estimated_legs_without_using_zero():
    legs = [
        {
            "origin": {"latitude": 37.48, "longitude": 126.93},
            "destination": {"latitude": 37.49, "longitude": 126.94},
        }
    ]
    with patch.object(
        route_travel_time,
        "get_travel",
        return_value={
            "mode": "walk",
            "duration_min": 17,
            "paths": [],
            "calculation_status": "estimated",
        },
    ):
        result = route_travel_time.calculate_route_travel_times(legs)

    assert result["total_travel_time_minutes"] == 17
    assert result["estimated_leg_count"] == 1
    assert result["legs"][0]["calculation_status"] == "estimated"


def test_tmap_quota_error_opens_breaker():
    response = Mock(status_code=429)
    error = map_service.requests.HTTPError(response=response)
    previous_key = map_service.TMAP_APP_KEY
    map_service.TMAP_APP_KEY = "test-key"
    map_service._TMAP_BREAKER_OPEN_UNTIL = 0
    try:
        with patch.object(map_service.requests, "post", side_effect=error):
            assert map_service.get_tmap_walking(126.93, 37.48, 126.94, 37.49) is None
        assert map_service._TMAP_BREAKER_OPEN_UNTIL > map_service.monotonic()
    finally:
        map_service.TMAP_APP_KEY = previous_key
        map_service._TMAP_BREAKER_OPEN_UNTIL = 0
