import unittest
from unittest.mock import patch

from course_order_optimizer import optimize_course_order


def location(name, longitude, activity="cafe"):
    return {
        "name": name,
        "activity": activity,
        "latitude": 37.0,
        "longitude": longitude,
    }


def distance_based_travel(
    start_x,
    start_y,
    end_x,
    end_y,
    transport_mode="auto",
):
    return {"duration_min": abs(end_x - start_x) * 10}


class CourseOrderOptimizerTest(unittest.TestCase):
    @patch("route_travel_time.get_travel", side_effect=distance_based_travel)
    def test_single_place_is_evaluated_without_permutation(self, mock_get_travel):
        place = location("A", 1.0, activity="food")

        result = optimize_course_order(
            location("start", 0.0),
            [place],
            available_time_minutes=100,
        )

        self.assertEqual(result["optimized_places"], [place])
        self.assertEqual(result["total_travel_time_minutes"], 10)
        self.assertEqual(result["total_stay_time_minutes"], 60)
        self.assertEqual(result["status"], "FEASIBLE")
        mock_get_travel.assert_called_once()

    @patch("route_travel_time.get_travel", side_effect=distance_based_travel)
    def test_selects_shortest_order_without_end_location(self, mock_get_travel):
        places = [
            location("A", 3.0),
            location("B", 1.0),
            location("C", 2.0),
        ]

        result = optimize_course_order(
            location("start", 0.0),
            places,
            available_time_minutes=200,
        )

        self.assertEqual(
            [place["name"] for place in result["optimized_places"]],
            ["B", "C", "A"],
        )
        self.assertEqual(result["total_travel_time_minutes"], 30)
        self.assertEqual(result["legs"][-1]["destination"]["longitude"], 3.0)

    @patch("route_travel_time.get_travel", side_effect=distance_based_travel)
    def test_preferred_first_stays_first_and_remaining_order_is_optimized(
        self,
        mock_get_travel,
    ):
        places = [
            location("A", 1.0),
            {**location("B", 3.0), "preferred_first": True},
            location("C", 2.0),
        ]

        result = optimize_course_order(
            location("start", 0.0),
            places,
            available_time_minutes=200,
        )

        self.assertEqual(
            [place["name"] for place in result["optimized_places"]],
            ["B", "C", "A"],
        )
        self.assertCountEqual(result["optimized_places"], places)

    @patch("route_travel_time.get_travel")
    def test_preferred_first_skips_failed_order_and_keeps_complete_places(
        self,
        mock_get_travel,
    ):
        def travel_with_failed_b_to_a(
            start_x,
            start_y,
            end_x,
            end_y,
            transport_mode="auto",
        ):
            if (start_x, end_x) == (3.0, 1.0):
                return None
            return {"duration_min": abs(end_x - start_x) * 10}

        mock_get_travel.side_effect = travel_with_failed_b_to_a
        places = [
            location("A", 1.0),
            {**location("B", 3.0), "preferred_first": True},
            location("C", 2.0),
        ]

        result = optimize_course_order(
            location("start", 0.0),
            places,
            available_time_minutes=200,
        )

        self.assertEqual(
            [place["name"] for place in result["optimized_places"]],
            ["B", "C", "A"],
        )
        self.assertCountEqual(result["optimized_places"], places)
        failed_leg_calls = [
            mock_call
            for mock_call in mock_get_travel.call_args_list
            if mock_call.args[:4] == (3.0, 37.0, 1.0, 37.0)
        ]
        self.assertEqual(len(failed_leg_calls), 1)

    @patch("route_travel_time.get_travel", return_value=None)
    def test_preferred_first_fails_when_all_complete_orders_fail(
        self,
        mock_get_travel,
    ):
        with self.assertRaisesRegex(RuntimeError, "모든 방문 순서"):
            optimize_course_order(
                location("start", 0.0),
                [
                    location("A", 1.0),
                    {**location("B", 2.0), "preferred_first": True},
                    location("C", 3.0),
                ],
                available_time_minutes=200,
            )

        self.assertEqual(mock_get_travel.call_count, 1)

    @patch("route_travel_time.get_travel", side_effect=distance_based_travel)
    def test_keeps_end_location_fixed(self, mock_get_travel):
        result = optimize_course_order(
            location("start", 0.0),
            [location("A", 3.0), location("B", 1.0), location("C", 2.0)],
            available_time_minutes=200,
            end_location=location("end", 4.0),
        )

        self.assertEqual(
            [place["name"] for place in result["optimized_places"]],
            ["B", "C", "A"],
        )
        self.assertEqual(result["total_travel_time_minutes"], 40)
        self.assertEqual(result["legs"][-1]["destination"]["longitude"], 4.0)

    @patch("route_travel_time.get_travel", side_effect=distance_based_travel)
    def test_reuses_each_directed_leg_across_permutations(self, mock_get_travel):
        optimize_course_order(
            location("start", 0.0),
            [location("A", 1.0), location("B", 2.0), location("C", 3.0)],
            available_time_minutes=200,
        )

        self.assertEqual(mock_get_travel.call_count, 9)
        call_keys = [
            (mock_call.args, tuple(mock_call.kwargs.items()))
            for mock_call in mock_get_travel.call_args_list
        ]
        self.assertEqual(
            len(set(call_keys)),
            mock_get_travel.call_count,
        )

    @patch("route_travel_time.get_travel")
    def test_skips_failed_order_and_reuses_failed_directed_leg(
        self,
        mock_get_travel,
    ):
        def travel_with_failed_a_to_b(
            start_x,
            start_y,
            end_x,
            end_y,
            transport_mode="auto",
        ):
            if (start_x, end_x) == (1.0, 2.0):
                return None
            return {"duration_min": abs(end_x - start_x) * 10}

        mock_get_travel.side_effect = travel_with_failed_a_to_b
        places = [
            location("A", 1.0),
            location("B", 2.0),
            location("C", 3.0),
        ]

        result = optimize_course_order(
            location("start", 0.0),
            places,
            available_time_minutes=200,
        )

        self.assertEqual(
            [place["name"] for place in result["optimized_places"]],
            ["A", "C", "B"],
        )
        self.assertCountEqual(result["optimized_places"], places)
        failed_leg_calls = [
            mock_call
            for mock_call in mock_get_travel.call_args_list
            if mock_call.args[:4] == (1.0, 37.0, 2.0, 37.0)
        ]
        self.assertEqual(len(failed_leg_calls), 1)

    @patch("route_travel_time.get_travel", return_value=None)
    def test_fails_only_when_all_complete_orders_fail(self, mock_get_travel):
        with self.assertRaisesRegex(RuntimeError, "모든 방문 순서"):
            optimize_course_order(
                location("start", 0.0),
                [
                    location("A", 1.0),
                    location("B", 2.0),
                    location("C", 3.0),
                ],
                available_time_minutes=200,
            )

        self.assertEqual(mock_get_travel.call_count, 3)

    def test_rejects_more_than_six_places(self):
        with self.assertRaisesRegex(ValueError, "최대 6개"):
            optimize_course_order(
                location("start", 0.0),
                [location(str(index), float(index)) for index in range(1, 8)],
                available_time_minutes=500,
            )


if __name__ == "__main__":
    unittest.main()
