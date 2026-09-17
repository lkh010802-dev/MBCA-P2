import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from adventure_service import (
    MAX_GACHA_VALIDATION_CANDIDATES,
    NoAdventureCandidateError,
    recommend_single_place_gacha,
)
from main import app
from models import AdventureRequest, CourseCalculationRequest


client = TestClient(app)


def adventure_request(**context_overrides):
    context = {
        "activities": ["cafe"],
        "activity_preferences": {"cafe": 5},
        "space_preference": "indoor",
        "transport_mode": "walk",
        "start_location": {"latitude": 37.5, "longitude": 127.0},
        "departure_datetime": "2026-09-11T15:00:00+09:00",
        "end_location": None,
        "available_time_minutes": 120,
    }
    context.update(context_overrides)
    return AdventureRequest(
        area={
            "area_name": "성수동",
            "latitude": 37.544,
            "longitude": 127.056,
        },
        recommendation_context=context,
    )


def place(name, category="cafe"):
    return {
        "source": "kakao",
        "source_id": name,
        "name": name,
        "category": category,
        "latitude": 37.51,
        "longitude": 127.01,
        "distance_m": 100,
        "place_score": 95.0,
        "operation_schedule": [],
        "operation_schedule_status": "missing",
    }


def course_result(request, status="FEASIBLE", availability_status="unknown"):
    selected_place = request.selected_places[0].model_dump()
    selected_place["availability"] = {
        "status": availability_status,
        "arrival_at": datetime(2026, 9, 11, 15, 10, tzinfo=timezone.utc),
        "opening_at": None,
        "closing_at": None,
        "remaining_minutes": None,
    }
    return {
        "optimized_places": [selected_place],
        "legs": [],
        "total_travel_time_minutes": 10,
        "total_stay_time_minutes": 45,
        "total_required_minutes": 55,
        "available_time_minutes": request.available_time_minutes,
        "remaining_time_minutes": request.available_time_minutes - 55,
        "status": status,
    }


class AdventureRequestValidationTests(unittest.TestCase):
    def test_rejects_invalid_coordinates(self):
        payload = adventure_request().model_dump(mode="json")
        payload["area"]["latitude"] = 91

        response = client.post("/recommend/adventure", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_rejects_non_positive_available_time(self):
        with self.assertRaises(ValidationError):
            adventure_request(available_time_minutes=0)

    def test_rejects_naive_departure_datetime(self):
        with self.assertRaises(ValidationError):
            adventure_request(departure_datetime="2026-09-11T15:00:00")


class AdventureServiceTests(unittest.TestCase):
    @patch("map_service.get_transit", return_value=None)
    @patch(
        "map_service.get_walking",
        return_value={"mode": "walk", "duration_min": 2},
    )
    def test_nearby_public_transit_candidate_uses_walking_fallback(
        self,
        mock_walking,
        mock_transit,
    ):
        nearby_place = place("A")
        nearby_place["latitude"] = 37.5
        nearby_place["longitude"] = 127.001

        result = recommend_single_place_gacha(
            adventure_request(transport_mode="public_transit"),
            recommend_places_fn=Mock(return_value=[nearby_place]),
            choice_fn=lambda candidates: candidates[0],
        )

        self.assertEqual(result["place"]["name"], "A")
        self.assertEqual(result["availability"]["status"], "unknown")
        self.assertEqual(result["course_preview"]["total_travel_time_minutes"], 2)
        mock_transit.assert_called_once()
        mock_walking.assert_called_once()

    def test_calls_recommend_places_once_with_context(self):
        recommend_places = Mock(return_value=[place("A")])

        result = recommend_single_place_gacha(
            adventure_request(),
            recommend_places_fn=recommend_places,
            calculate_course_fn=lambda request, _: course_result(request),
            choice_fn=lambda candidates: candidates[0],
        )

        recommend_places.assert_called_once_with(
            area_name="성수동",
            latitude=37.544,
            longitude=127.056,
            activities=["cafe"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference="indoor",
            activity_preferences={"cafe": 5},
        )
        self.assertEqual(result["place"]["name"], "A")

    def test_validates_only_first_three_places_in_original_order(self):
        places = [place(name) for name in ("A", "B", "C", "D")]
        validated_names = []

        def calculate_course(request, _):
            validated_names.append(request.selected_places[0].name)
            return course_result(request)

        recommend_single_place_gacha(
            adventure_request(),
            recommend_places_fn=Mock(return_value=places),
            calculate_course_fn=calculate_course,
            choice_fn=lambda candidates: candidates[0],
        )

        self.assertEqual(MAX_GACHA_VALIDATION_CANDIDATES, 3)
        self.assertEqual(validated_names, ["A", "B", "C"])

    def test_stay_time_failure_skips_course(self):
        calculate_course = Mock()

        with self.assertRaises(NoAdventureCandidateError):
            recommend_single_place_gacha(
                adventure_request(available_time_minutes=20),
                recommend_places_fn=Mock(return_value=[place("A")]),
                calculate_course_fn=calculate_course,
            )

        calculate_course.assert_not_called()

    def test_infeasible_course_is_excluded(self):
        with self.assertRaises(NoAdventureCandidateError):
            recommend_single_place_gacha(
                adventure_request(),
                recommend_places_fn=Mock(return_value=[place("A")]),
                calculate_course_fn=(
                    lambda request, _: course_result(request, status="INFEASIBLE")
                ),
            )

    def test_explicitly_unavailable_statuses_are_excluded(self):
        for status in (
            "closed",
            "event_ended",
            "event_not_started",
            "not_yet_open",
        ):
            with self.subTest(status=status):
                with self.assertRaises(NoAdventureCandidateError):
                    recommend_single_place_gacha(
                        adventure_request(),
                        recommend_places_fn=Mock(return_value=[place("A")]),
                        calculate_course_fn=(
                            lambda request, _, status=status: course_result(
                                request,
                                availability_status=status,
                            )
                        ),
                    )

    def test_open_candidates_take_priority_over_unknown(self):
        places = [place("unknown"), place("open")]

        def calculate_course(request, _):
            name = request.selected_places[0].name
            return course_result(request, availability_status=name)

        result = recommend_single_place_gacha(
            adventure_request(),
            recommend_places_fn=Mock(return_value=places),
            calculate_course_fn=calculate_course,
            choice_fn=lambda candidates: candidates[0],
        )

        self.assertEqual(result["place"]["name"], "open")
        self.assertTrue(result["availability_confirmed"])

    def test_unknown_is_used_only_as_fallback(self):
        result = recommend_single_place_gacha(
            adventure_request(),
            recommend_places_fn=Mock(return_value=[place("A")]),
            calculate_course_fn=lambda request, _: course_result(request),
            choice_fn=lambda candidates: candidates[0],
        )

        self.assertEqual(result["availability"]["status"], "unknown")
        self.assertFalse(result["availability_confirmed"])

    def test_random_choice_receives_only_validated_candidates(self):
        places = [place("closed"), place("open"), place("infeasible")]
        choice = Mock(side_effect=lambda candidates: candidates[0])

        def calculate_course(request, _):
            name = request.selected_places[0].name
            return course_result(
                request,
                status="INFEASIBLE" if name == "infeasible" else "FEASIBLE",
                availability_status=("closed" if name == "closed" else "open"),
            )

        result = recommend_single_place_gacha(
            adventure_request(),
            recommend_places_fn=Mock(return_value=places),
            calculate_course_fn=calculate_course,
            choice_fn=choice,
        )

        self.assertEqual(result["place"]["name"], "open")
        self.assertEqual(
            [candidate["place"]["name"] for candidate in choice.call_args.args[0]],
            ["open"],
        )

    def test_course_request_is_ready_for_existing_course_endpoint(self):
        result = recommend_single_place_gacha(
            adventure_request(),
            recommend_places_fn=Mock(return_value=[place("A")]),
            calculate_course_fn=lambda request, _: course_result(request),
            choice_fn=lambda candidates: candidates[0],
        )

        validated = CourseCalculationRequest.model_validate(
            result["course_request"]
        )
        selected = validated.selected_places[0]
        self.assertEqual(selected.name, "A")
        self.assertEqual(selected.category, "cafe")
        self.assertEqual(selected.operation_schedule_status, "missing")
        self.assertIsNotNone(validated.departure_datetime.utcoffset())

    def test_travel_failure_is_a_candidate_failure(self):
        def calculate_course(_request, _optimizer):
            raise HTTPException(status_code=502, detail="travel failed")

        with self.assertRaises(NoAdventureCandidateError):
            recommend_single_place_gacha(
                adventure_request(),
                recommend_places_fn=Mock(return_value=[place("A")]),
                calculate_course_fn=calculate_course,
            )

    def test_unexpected_course_error_is_not_hidden(self):
        def calculate_course(_request, _optimizer):
            raise RuntimeError("bug")

        with self.assertRaisesRegex(RuntimeError, "bug"):
            recommend_single_place_gacha(
                adventure_request(),
                recommend_places_fn=Mock(return_value=[place("A")]),
                calculate_course_fn=calculate_course,
            )


class AdventureApiTests(unittest.TestCase):
    @patch("adventure_routes.recommend_single_place_gacha")
    def test_returns_valid_adventure_response(self, recommend_gacha):
        request = adventure_request()
        recommend_gacha.return_value = recommend_single_place_gacha(
            request,
            recommend_places_fn=Mock(return_value=[place("A")]),
            calculate_course_fn=lambda course_request, _: course_result(
                course_request,
                availability_status="open",
            ),
            choice_fn=lambda candidates: candidates[0],
        )

        response = client.post(
            "/recommend/adventure",
            json=request.model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["place"]["name"], "A")
        self.assertTrue(body["availability_confirmed"])
        CourseCalculationRequest.model_validate(body["course_request"])

    @patch("adventure_routes.recommend_single_place_gacha")
    def test_returns_404_when_no_candidate_exists(self, recommend_gacha):
        recommend_gacha.side_effect = NoAdventureCandidateError

        response = client.post(
            "/recommend/adventure",
            json=adventure_request().model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "현재 조건에서 방문 가능한 가챠 후보가 없습니다.",
        )


if __name__ == "__main__":
    unittest.main()
