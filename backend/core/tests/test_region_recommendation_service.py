import unittest
from unittest.mock import Mock

from region_recommendation_service import _get_candidate_travel_pair


class RegionTravelPairTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "AREA_CD": "A",
            "longitude": 127.01,
            "latitude": 37.51,
        }
        self.start_location = {"x": 127.0, "y": 37.5}
        self.end_location = {"x": 127.1, "y": 37.6}

    def calculate(self, get_travel, *, end_location=None):
        return _get_candidate_travel_pair(
            self.candidate,
            start_location=self.start_location,
            end_location=end_location,
            transport_mode="public_transit",
            get_travel_fn=get_travel,
        )

    def test_calls_end_leg_only_after_start_leg_succeeds(self):
        travel = Mock(side_effect=[None])

        self.assertIsNone(
            self.calculate(travel, end_location=self.end_location)
        )
        travel.assert_called_once_with(
            127.0,
            37.5,
            127.01,
            37.51,
            transport_mode="public_transit",
        )

    def test_excludes_candidate_when_end_leg_fails(self):
        travel = Mock(side_effect=[{"duration_min": 12}, None])

        self.assertIsNone(
            self.calculate(travel, end_location=self.end_location)
        )
        self.assertEqual(travel.call_count, 2)

    def test_without_end_location_calls_only_start_leg(self):
        travel = Mock(return_value={"duration_min": 12})

        result = self.calculate(travel)

        self.assertEqual(
            result,
            ({"duration_min": 12}, {"duration_min": 0}),
        )
        travel.assert_called_once()

    def test_unexpected_exception_is_not_hidden(self):
        travel = Mock(side_effect=RuntimeError("unexpected"))

        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            self.calculate(travel, end_location=self.end_location)


if __name__ == "__main__":
    unittest.main()
