import unittest
from unittest.mock import patch

from course_time_evaluator import FEASIBLE, INFEASIBLE, evaluate_course_time


class CourseTimeEvaluatorTest(unittest.TestCase):
    @patch("course_time_evaluator.calculate_route_travel_times")
    @patch("course_time_evaluator.build_travel_legs")
    @patch("course_time_evaluator.validate_selected_places_stay_time")
    def test_feasible_when_required_time_is_within_available_time(
        self,
        mock_validate_stay_time,
        mock_build_legs,
        mock_calculate_travel_times,
    ):
        mock_validate_stay_time.return_value = {
            "total_stay_duration_minutes": 90,
        }
        mock_build_legs.return_value = ["leg"]
        mock_calculate_travel_times.return_value = {
            "legs": ["leg_with_time"],
            "total_travel_time_minutes": 30,
        }

        result = evaluate_course_time(
            {"latitude": 37.1, "longitude": 127.1},
            [{"activity": "cafe", "latitude": 37.2, "longitude": 127.2}],
            available_time_minutes=120,
            transport_mode="public_transit",
        )

        self.assertEqual(
            result,
            {
                "legs": ["leg_with_time"],
                "total_stay_time_minutes": 90,
                "total_travel_time_minutes": 30,
                "total_required_minutes": 120,
                "available_time_minutes": 120,
                "remaining_time_minutes": 0,
                "status": FEASIBLE,
            },
        )
        mock_calculate_travel_times.assert_called_once_with(
            ["leg"],
            "public_transit",
        )

    @patch("course_time_evaluator.calculate_route_travel_times")
    @patch("course_time_evaluator.build_travel_legs", return_value=[])
    @patch("course_time_evaluator.validate_selected_places_stay_time")
    def test_infeasible_keeps_negative_remaining_time(
        self,
        mock_validate_stay_time,
        mock_build_legs,
        mock_calculate_travel_times,
    ):
        mock_validate_stay_time.return_value = {
            "total_stay_duration_minutes": 100,
        }
        mock_calculate_travel_times.return_value = {
            "legs": [],
            "total_travel_time_minutes": 40,
        }

        result = evaluate_course_time(
            {"latitude": 37.1, "longitude": 127.1},
            [],
            available_time_minutes=120,
        )

        self.assertEqual(result["total_required_minutes"], 140)
        self.assertEqual(result["remaining_time_minutes"], -20)
        self.assertEqual(result["status"], INFEASIBLE)


if __name__ == "__main__":
    unittest.main()
