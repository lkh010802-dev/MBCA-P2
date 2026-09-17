import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import app, calculate_course
from models import CourseCalculationRequest


def course_request(
    selected_places,
    end_location=None,
    available_time_minutes=180,
    transport_mode="auto",
    departure_datetime=None,
):
    return CourseCalculationRequest(
        start_location={"latitude": 37.0, "longitude": 127.0},
        selected_places=selected_places,
        available_time_minutes=available_time_minutes,
        departure_datetime=departure_datetime,
        end_location=end_location,
        transport_mode=transport_mode,
    )


def place(name, longitude, preferred_first=False, **overrides):
    value = {
        "name": name,
        "category": "cafe",
        "latitude": 37.0,
        "longitude": longitude,
        "preferred_first": preferred_first,
    }
    value.update(overrides)
    return value


def course_result(status="FEASIBLE"):
    return {
        "optimized_places": [],
        "legs": [],
        "total_travel_time_minutes": 20,
        "total_stay_time_minutes": 45,
        "total_required_minutes": 65,
        "available_time_minutes": 180,
        "remaining_time_minutes": 115,
        "status": status,
    }


class CourseApiTest(unittest.TestCase):
    @patch("main.optimize_course_order")
    def test_single_place_without_end_location(self, mock_optimize):
        mocked_result = course_result()
        mocked_result["optimized_places"] = [
            {
                "name": "A",
                "category": "cafe",
                "activity": "cafe",
                "latitude": 37.0,
                "longitude": 127.1,
                "preferred_first": True,
            }
        ]
        mock_optimize.return_value = mocked_result

        result = calculate_course(
            course_request([place("A", 127.1, preferred_first=True)])
        )

        self.assertEqual(result["status"], "FEASIBLE")

        # optimizer 내부에는 체류시간 계산용 activity가 전달된다.
        kwargs = mock_optimize.call_args.kwargs
        self.assertEqual(len(kwargs["selected_places"]), 1)
        self.assertEqual(kwargs["selected_places"][0]["activity"], "cafe")
        self.assertTrue(kwargs["selected_places"][0]["preferred_first"])
        self.assertIsNone(kwargs["end_location"])

        # 최종 API 응답에서는 내부 계산용 activity를 제거한다.
        self.assertNotIn("activity", result["optimized_places"][0])
        self.assertNotIn("preferred_first", result["optimized_places"][0])
        self.assertNotIn("availability", result["optimized_places"][0])
        self.assertEqual(result["optimized_places"][0]["category"], "cafe")

    def test_accepts_timezone_aware_departure_datetime(self):
        request = course_request(
            [place("A", 127.1)],
            departure_datetime=datetime(2026, 9, 8, 9, tzinfo=timezone.utc),
        )

        self.assertIsNotNone(request.departure_datetime.utcoffset())

    @patch("main.optimize_course_order")
    def test_recalculates_proactive_place_availability_from_preserved_schedule(
        self,
        mock_optimize,
    ):
        departure = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)
        proactive_place = place(
            "행사",
            127.1,
            source="popup",
            source_id="popup-1",
            start_at="2026-09-01",
            end_at="2026-09-30",
            operation_schedule_status="parsed",
            operation_schedule=[{
                "days": ["TUE"],
                "opening_time": "10:00",
                "closing_time": "20:00",
                "closed": False,
                "closes_next_day": False,
            }],
        )

        def optimize(**kwargs):
            return {
                **course_result(),
                "optimized_places": kwargs["selected_places"],
                "legs": [{"travel_time_minutes": 10}],
            }

        mock_optimize.side_effect = optimize
        result = calculate_course(
            course_request(
                [proactive_place],
                departure_datetime=departure,
            )
        )

        optimized_place = result["optimized_places"][0]
        self.assertEqual(optimized_place["operation_schedule_status"], "parsed")
        self.assertEqual(
            optimized_place["operation_schedule"],
            proactive_place["operation_schedule"],
        )
        self.assertEqual(optimized_place["availability"]["status"], "open")

    def test_rejects_naive_departure_datetime_with_422(self):
        response = TestClient(app).post(
            "/recommend/course",
            json={
                "start_location": {"latitude": 37.0, "longitude": 127.0},
                "selected_places": [place("A", 127.1)],
                "available_time_minutes": 180,
                "departure_datetime": "2026-09-08T09:00:00",
            },
        )

        self.assertEqual(response.status_code, 422)

    @patch("route_travel_time.get_travel")
    @patch("course_routes.evaluate_place_availability")
    @patch("main.optimize_course_order")
    def test_adds_availability_using_existing_legs_and_accumulated_stay_time(
        self,
        mock_optimize,
        mock_availability,
        mock_get_travel,
    ):
        departure = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)
        optimized_places = [
            place(
                "A",
                127.1,
                preferred_first=True,
                activity="cafe",
                specified_duration_minutes=20,
            ),
            place("B", 127.2, activity="cafe"),
            place("C", 127.3, activity="cafe"),
        ]
        mock_optimize.return_value = {
            **course_result("FEASIBLE"),
            "optimized_places": optimized_places,
            "legs": [
                {"travel_time_minutes": 5},
                {"travel_time_minutes": 10},
                {"travel_time_minutes": 15},
                {"travel_time_minutes": 99},
            ],
        }
        statuses = iter(("open", "closed", "unknown"))

        def availability(place_data, current, travel_minutes):
            arrival = current + timedelta(minutes=travel_minutes)
            return {
                "status": next(statuses),
                "arrival_at": arrival,
                "opening_at": None,
                "closing_at": None,
                "remaining_minutes": None,
            }

        mock_availability.side_effect = availability
        result = calculate_course(
            course_request(
                [
                    place("A", 127.1, preferred_first=True, specified_duration_minutes=20),
                    place("B", 127.2),
                    place("C", 127.3),
                ],
                end_location={"latitude": 37.5, "longitude": 127.5},
                departure_datetime=departure,
            )
        )

        self.assertEqual(
            [item["availability"]["status"] for item in result["optimized_places"]],
            ["open", "closed", "unknown"],
        )
        self.assertEqual(
            result["optimized_places"][0]["availability"]["arrival_at"],
            departure + timedelta(minutes=5),
        )
        self.assertEqual(
            result["optimized_places"][1]["availability"]["arrival_at"],
            departure + timedelta(minutes=5 + 20 + 10),
        )
        self.assertEqual(
            result["optimized_places"][2]["availability"]["arrival_at"],
            departure + timedelta(minutes=5 + 20 + 10 + 45 + 15),
        )
        self.assertEqual(result["status"], "FEASIBLE")
        self.assertNotIn("activity", result["optimized_places"][0])
        self.assertNotIn("preferred_first", result["optimized_places"][0])
        self.assertEqual(mock_availability.call_count, 3)
        mock_get_travel.assert_not_called()

    @patch("main.optimize_course_order")
    def test_multiple_places_with_fixed_end_location(self, mock_optimize):
        expected = course_result()
        expected["optimized_places"] = [place("B", 127.2), place("A", 127.1)]
        mock_optimize.return_value = expected
        end = {"latitude": 37.5, "longitude": 127.5}

        result = calculate_course(
            course_request(
                [place("A", 127.1), place("B", 127.2)],
                end_location=end,
                transport_mode="public_transit",
            )
        )

        self.assertEqual(result, expected)
        kwargs = mock_optimize.call_args.kwargs
        self.assertEqual(kwargs["end_location"], end)
        self.assertEqual(kwargs["transport_mode"], "public_transit")

    @patch("main.optimize_course_order")
    def test_returns_infeasible_result_unchanged(self, mock_optimize):
        expected = course_result("INFEASIBLE")
        expected["remaining_time_minutes"] = -10
        mock_optimize.return_value = expected

        result = calculate_course(course_request([place("A", 127.1)]))

        self.assertEqual(result["status"], "INFEASIBLE")
        self.assertEqual(result["remaining_time_minutes"], -10)

    @patch("course_routes.evaluate_place_availability")
    @patch("main.optimize_course_order")
    def test_availability_does_not_change_infeasible_status(
        self,
        mock_optimize,
        mock_availability,
    ):
        departure = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)
        optimized_place = place("A", 127.1, activity="cafe")
        mock_optimize.return_value = {
            **course_result("INFEASIBLE"),
            "optimized_places": [optimized_place],
            "legs": [{"travel_time_minutes": 10}],
        }
        mock_availability.return_value = {
            "status": "closed",
            "arrival_at": departure + timedelta(minutes=10),
            "opening_at": None,
            "closing_at": None,
            "remaining_minutes": None,
        }

        result = calculate_course(
            course_request(
                [place("A", 127.1)],
                departure_datetime=departure,
            )
        )

        self.assertEqual(result["status"], "INFEASIBLE")
        self.assertEqual(
            result["optimized_places"][0]["availability"]["status"],
            "closed",
        )

    def test_rejects_more_than_six_places_in_request_model(self):
        with self.assertRaises(ValidationError):
            course_request(
                [place(str(index), 127.0 + index / 100) for index in range(7)]
            )

    def test_rejects_multiple_preferred_first_places(self):
        with self.assertRaisesRegex(ValidationError, "최대 1개"):
            course_request([
                place("A", 127.1, preferred_first=True),
                place("B", 127.2, preferred_first=True),
            ])

    @patch("main.optimize_course_order", side_effect=RuntimeError("이동시간 실패"))
    def test_returns_bad_gateway_when_travel_calculation_fails(
        self,
        mock_optimize,
    ):
        with self.assertRaises(HTTPException) as context:
            calculate_course(course_request([place("A", 127.1)]))

        self.assertEqual(context.exception.status_code, 502)
        self.assertEqual(context.exception.detail, "이동시간 실패")

    def test_request_model_rejects_invalid_input(self):
        invalid_payloads = [
            {"selected_places": []},
            {
                "selected_places": [place("A", 127.1)],
                "start_location": {"latitude": 91, "longitude": 127.0},
            },
            {"selected_places": [place("A", 127.1)], "available_time_minutes": 0},
            {"selected_places": [place("A", 127.1)], "transport_mode": "bike"},
        ]

        for changes in invalid_payloads:
            payload = {
                "start_location": {"latitude": 37.0, "longitude": 127.0},
                "selected_places": [place("A", 127.1)],
                "available_time_minutes": 180,
            } | changes
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    CourseCalculationRequest(**payload)


if __name__ == "__main__":
    unittest.main()
