from unittest.mock import patch

from map_service import get_travel


def test_same_point_is_zero_minutes_without_external_route_call():
    with patch("map_service.get_walking") as walking:
        result = get_travel(126.9291, 37.4842, 126.9291, 37.4842, "walk")

    walking.assert_not_called()
    assert result["duration_min"] == 0
    assert result["distance_m"] == 0
    assert result["mode"] == "walk"
