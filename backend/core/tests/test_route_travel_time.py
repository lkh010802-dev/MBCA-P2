import unittest
from unittest.mock import call, patch

from route_travel_time import calculate_route_travel_times


class RouteTravelTimeTest(unittest.TestCase):
    @patch("route_travel_time.get_travel")
    def test_adds_travel_time_to_each_leg_and_returns_total(self, mock_get_travel):
        mock_get_travel.side_effect = [
            {"duration_min": 12},
            {"duration_min": 18},
        ]
        legs = [
            {
                "origin": {"latitude": 37.1, "longitude": 127.1},
                "destination": {"latitude": 37.2, "longitude": 127.2},
            },
            {
                "origin": {"latitude": 37.2, "longitude": 127.2},
                "destination": {"latitude": 37.3, "longitude": 127.3},
            },
        ]

        result = calculate_route_travel_times(legs, "public_transit")

        self.assertEqual(
            [leg["travel_time_minutes"] for leg in result["legs"]],
            [12, 18],
        )
        self.assertEqual(result["total_travel_time_minutes"], 30)
        self.assertEqual(
            mock_get_travel.call_args_list,
            [
                call(127.1, 37.1, 127.2, 37.2, transport_mode="public_transit"),
                call(127.2, 37.2, 127.3, 37.3, transport_mode="public_transit"),
            ],
        )

    @patch("route_travel_time.get_travel", return_value=None)
    def test_raises_clear_error_when_travel_api_fails(self, mock_get_travel):
        leg = {
            "origin": {"latitude": 37.1, "longitude": 127.1},
            "destination": {"latitude": 37.2, "longitude": 127.2},
        }

        with self.assertRaisesRegex(RuntimeError, "leg_index=0"):
            calculate_route_travel_times([leg])

    @patch("route_travel_time.get_travel", return_value={"mode": "walk"})
    def test_raises_clear_error_when_duration_is_missing(self, mock_get_travel):
        leg = {
            "origin": {"latitude": 37.1, "longitude": 127.1},
            "destination": {"latitude": 37.2, "longitude": 127.2},
        }

        with self.assertRaisesRegex(RuntimeError, "leg_index=0"):
            calculate_route_travel_times([leg])

    @patch("route_travel_time.get_travel", return_value={"duration_min": 12})
    def test_reuses_cached_leg_travel_time(self, mock_get_travel):
        leg = {
            "origin": {"latitude": 37.1, "longitude": 127.1},
            "destination": {"latitude": 37.2, "longitude": 127.2},
        }
        cache = {}

        calculate_route_travel_times([leg], travel_cache=cache)
        calculate_route_travel_times([leg], travel_cache=cache)

        mock_get_travel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
