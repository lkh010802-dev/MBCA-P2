import unittest
from unittest.mock import Mock, patch

import requests

import map_service


class TravelModeTests(unittest.TestCase):

    @patch("map_service.get_walking")
    def test_walk_uses_walking_route(self, mock_walking):
        mock_walking.return_value = {"mode": "walk"}

        result = map_service.get_travel(
            126.9,
            37.5,
            127.0,
            37.6,
            transport_mode="walk",
        )

        self.assertEqual(result["mode"], "walk")
        mock_walking.assert_called_once()

    @patch("map_service.get_transit")
    @patch("map_service.get_walking")
    @patch("map_service.is_nearby")
    def test_public_transit_uses_transit_route_without_walking_fallback(
        self,
        mock_nearby,
        mock_walking,
        mock_transit,
    ):
        mock_transit.return_value = {"mode": "transit"}

        result = map_service.get_travel(
            126.9,
            37.5,
            127.0,
            37.6,
            transport_mode="public_transit",
        )

        self.assertEqual(result["mode"], "transit")
        mock_transit.assert_called_once()
        mock_nearby.assert_not_called()
        mock_walking.assert_not_called()

    @patch("map_service.get_transit", return_value=None)
    @patch("map_service.get_walking", return_value={"mode": "walk"})
    @patch("map_service.is_nearby", return_value=True)
    def test_public_transit_falls_back_to_walking_within_500m(
        self,
        mock_nearby,
        mock_walking,
        mock_transit,
    ):
        result = map_service.get_travel(
            126.9,
            37.5,
            126.901,
            37.5,
            transport_mode="public_transit",
        )

        self.assertEqual(result["mode"], "walk")
        mock_transit.assert_called_once()
        mock_nearby.assert_called_once_with(
            126.9,
            37.5,
            126.901,
            37.5,
            max_distance_km=0.5,
        )
        mock_walking.assert_called_once()

    @patch("map_service.get_transit", return_value=None)
    @patch("map_service.get_walking")
    @patch("map_service.is_nearby", return_value=False)
    def test_public_transit_failure_over_500m_does_not_walk(
        self,
        mock_nearby,
        mock_walking,
        mock_transit,
    ):
        result = map_service.get_travel(
            126.9,
            37.5,
            127.0,
            37.6,
            transport_mode="public_transit",
        )

        self.assertIsNone(result)
        mock_transit.assert_called_once()
        mock_nearby.assert_called_once()
        mock_walking.assert_not_called()

    @patch("map_service.get_transit", return_value=None)
    @patch("map_service.get_walking", return_value=None)
    @patch("map_service.is_nearby", return_value=True)
    def test_public_transit_walking_fallback_failure_returns_none(
        self,
        mock_nearby,
        mock_walking,
        mock_transit,
    ):
        result = map_service.get_travel(
            126.9,
            37.5,
            126.901,
            37.5,
            transport_mode="public_transit",
        )

        self.assertIsNone(result)
        mock_transit.assert_called_once()
        mock_nearby.assert_called_once()
        mock_walking.assert_called_once()

    @patch("map_service.get_driving")
    def test_car_uses_driving_route(self, mock_driving):
        mock_driving.return_value = {"mode": "car"}

        result = map_service.get_travel(
            126.9,
            37.5,
            127.0,
            37.6,
            transport_mode="car",
        )

        self.assertEqual(result["mode"], "car")
        mock_driving.assert_called_once()

    @patch("map_service.get_transit")
    @patch("map_service.get_walking")
    @patch("map_service.is_nearby", return_value=True)
    def test_auto_uses_walking_for_nearby_route(
        self,
        mock_nearby,
        mock_walking,
        mock_transit,
    ):
        mock_walking.return_value = {"mode": "walk"}

        result = map_service.get_travel(
            126.9,
            37.5,
            126.91,
            37.51,
            transport_mode="auto",
        )

        self.assertEqual(result["mode"], "walk")
        mock_nearby.assert_called_once()
        mock_walking.assert_called_once()
        mock_transit.assert_not_called()

    @patch("map_service.get_transit")
    @patch("map_service.get_walking")
    @patch("map_service.is_nearby", return_value=False)
    def test_auto_uses_transit_for_distant_route(
        self,
        mock_nearby,
        mock_walking,
        mock_transit,
    ):
        mock_transit.return_value = {"mode": "transit"}

        result = map_service.get_travel(
            126.9,
            37.5,
            127.1,
            37.6,
            transport_mode="auto",
        )

        self.assertEqual(result["mode"], "transit")
        mock_nearby.assert_called_once()
        mock_transit.assert_called_once()
        mock_walking.assert_not_called()

    def test_unsupported_transport_mode_returns_none(self):
        result = map_service.get_travel(
            126.9,
            37.5,
            127.0,
            37.6,
            transport_mode="bicycle",
        )

        self.assertIsNone(result)


class ExternalMapApiTests(unittest.TestCase):

    @patch("map_service.requests.get")
    def test_keyword_search_uses_nearby_distance_parameters(self, mock_get):
        response = Mock()
        response.json.return_value = {"documents": [{"place_name": "술집"}]}
        mock_get.return_value = response

        result = map_service.search_places_by_keyword(
            latitude=37.5,
            longitude=126.9,
            query="술집",
        )

        self.assertEqual(result, [{"place_name": "술집"}])
        self.assertEqual(
            mock_get.call_args.kwargs["params"],
            {
                "query": "술집",
                "x": 126.9,
                "y": 37.5,
                "radius": 2000,
                "size": 15,
                "sort": "distance",
            },
        )
        self.assertEqual(mock_get.call_args.kwargs["timeout"], 10)

    @patch("map_service.requests.get")
    def test_driving_response_is_normalized(self, mock_get):
        response = Mock()
        response.json.return_value = {
            "routes": [
                {
                    "result_code": 0,
                    "summary": {
                        "distance": 12387,
                        "duration": 2166,
                        "fare": {
                            "toll": 0,
                            "taxi": 17000,
                        },
                    },
                }
            ]
        }
        mock_get.return_value = response

        result = map_service.get_driving(
            126.9816,
            37.4765,
            127.1002,
            37.5133,
        )

        self.assertEqual(result["mode"], "car")
        self.assertEqual(result["distance_m"], 12387)
        self.assertEqual(result["duration_min"], 36)
        self.assertEqual(result["toll"], 0)
        self.assertEqual(mock_get.call_args.kwargs["timeout"], 10)

    @patch("map_service.requests.get")
    def test_driving_handles_very_close_route(self, mock_get):
        response = Mock()
        response.json.return_value = {
            "routes": [
                {
                    "result_code": 104,
                    "result_msg": "출발지와 목적지가 가까움",
                }
            ]
        }
        mock_get.return_value = response

        result = map_service.get_driving(
            127.0,
            37.5,
            127.0,
            37.5,
        )

        self.assertEqual(result["duration_min"], 0)
        self.assertEqual(result["distance_m"], 0)

    @patch(
        "map_service.requests.get",
        side_effect=requests.Timeout,
    )
    def test_driving_timeout_returns_none(self, mock_get):
        result = map_service.get_driving(
            126.9,
            37.5,
            127.0,
            37.6,
        )

        self.assertIsNone(result)
        mock_get.assert_called_once()

    @patch(
        "map_service.requests.get",
        side_effect=requests.Timeout,
    )
    def test_location_search_timeout_returns_none(self, mock_get):
        result = map_service.search_location("사당역")

        self.assertIsNone(result)
        mock_get.assert_called_once()

    @patch("map_service.requests.get")
    def test_invalid_transit_response_returns_none(self, mock_get):
        response = Mock()
        response.json.return_value = {
            "status": "OK",
            "routes": [],
        }
        mock_get.return_value = response

        result = map_service.get_transit(
            126.9,
            37.5,
            127.0,
            37.6,
        )

        self.assertIsNone(result)
        self.assertEqual(mock_get.call_args.kwargs["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
