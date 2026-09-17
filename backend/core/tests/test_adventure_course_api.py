import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from adventure_service import (
    MAX_COURSE_GACHA_PLACE_CANDIDATES,
    MAX_COURSE_GACHA_VALIDATION_COMBINATIONS,
    MIN_COURSE_GACHA_PLACE_DISTANCE_M,
    NoAdventureCandidateError,
    recommend_two_place_gacha,
)
from main import app
from models import AdventureRequest, CourseCalculationRequest


client = TestClient(app)


def adventure_request(**context_overrides):
    context = {
        "activities": ["cafe", "culture"],
        "activity_preferences": {},
        "space_preference": None,
        "transport_mode": "walk",
        "start_location": {"latitude": 37.5, "longitude": 127.0},
        "departure_datetime": "2026-09-14T15:00:00+09:00",
        "end_location": None,
        "available_time_minutes": 240,
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


def place(name, category="cafe", source_id=None, latitude=None, longitude=None):
    coordinate_index = ord(name[0].upper()) - ord("A")
    return {
        "source": "kakao",
        "source_id": source_id or name,
        "name": name,
        "category": category,
        "latitude": 37.5 if latitude is None else latitude,
        "longitude": (
            127.0 + coordinate_index * 0.003
            if longitude is None
            else longitude
        ),
        "operation_schedule": [],
        "operation_schedule_status": "missing",
    }


def course_result(request, statuses=("open", "open"), status="FEASIBLE"):
    optimized = []
    for index, selected in enumerate(reversed(request.selected_places)):
        value = selected.model_dump()
        value["availability"] = {
            "status": statuses[index],
            "arrival_at": datetime(2026, 9, 14, 6, 10, tzinfo=timezone.utc),
            "opening_at": None,
            "closing_at": None,
            "remaining_minutes": None,
        }
        optimized.append(value)
    return {
        "optimized_places": optimized,
        "legs": [],
        "total_travel_time_minutes": 20,
        "total_stay_time_minutes": 135,
        "total_required_minutes": 155,
        "available_time_minutes": request.available_time_minutes,
        "remaining_time_minutes": request.available_time_minutes - 155,
        "status": status,
    }


class AdventureCourseValidationTests(unittest.TestCase):
    def test_reuses_adventure_request_validation(self):
        with self.assertRaises(ValidationError):
            adventure_request(departure_datetime="2026-09-14T15:00:00")
        with self.assertRaises(ValidationError):
            adventure_request(available_time_minutes=0)


class AdventureCourseServiceTests(unittest.TestCase):
    def test_empty_place_result_raises_domain_error_before_validation(self):
        calculate = Mock()

        with self.assertRaises(NoAdventureCandidateError):
            recommend_two_place_gacha(
                adventure_request(),
                recommend_places_fn=Mock(return_value=[]),
                calculate_course_fn=calculate,
            )

        calculate.assert_not_called()

    def test_pair_under_200m_is_filtered_before_course_validation(self):
        calculate = Mock()
        nearby_places = [
            place("A", latitude=37.5, longitude=127.0),
            place("B", latitude=37.5017, longitude=127.0),
        ]

        with self.assertRaises(NoAdventureCandidateError):
            recommend_two_place_gacha(
                adventure_request(activities=["cafe"]),
                recommend_places_fn=Mock(return_value=nearby_places),
                calculate_course_fn=calculate,
            )

        self.assertEqual(MIN_COURSE_GACHA_PLACE_DISTANCE_M, 200)
        calculate.assert_not_called()

    @patch(
        "adventure_service._distance_between_places_m",
        return_value=MIN_COURSE_GACHA_PLACE_DISTANCE_M,
    )
    def test_pair_at_exactly_200m_can_reach_course_validation(self, _distance):
        calculate = Mock(side_effect=lambda request, _: course_result(request))

        result = recommend_two_place_gacha(
            adventure_request(activities=["cafe"]),
            recommend_places_fn=Mock(return_value=[place("A"), place("B")]),
            calculate_course_fn=calculate,
            choice_fn=lambda candidates: candidates[0],
        )

        calculate.assert_called_once()
        self.assertEqual(len(result["places"]), 2)

    def test_nearby_pair_is_skipped_while_separated_pair_is_validated(self):
        calculate = Mock(side_effect=lambda request, _: course_result(request))
        places = [
            place("A", latitude=37.5, longitude=127.0),
            place("B", latitude=37.5017, longitude=127.0),
            place("C", latitude=37.504, longitude=127.0),
        ]

        recommend_two_place_gacha(
            adventure_request(activities=["cafe"]),
            recommend_places_fn=Mock(return_value=places),
            calculate_course_fn=calculate,
            choice_fn=lambda candidates: candidates[0],
        )

        validated_pairs = [
            tuple(item.name for item in call.args[0].selected_places)
            for call in calculate.call_args_list
        ]
        self.assertNotIn(("A", "B"), validated_pairs)
        self.assertIn(("A", "C"), validated_pairs)

    def test_calls_recommend_places_once_and_returns_two_places(self):
        recommend_places = Mock(return_value=[
            place("A", "cafe"),
            place("B", "culture"),
        ])
        result = recommend_two_place_gacha(
            adventure_request(),
            recommend_places_fn=recommend_places,
            calculate_course_fn=lambda request, _: course_result(request),
            choice_fn=lambda candidates: candidates[0],
        )
        recommend_places.assert_called_once()
        self.assertEqual(len(result["places"]), 2)
        self.assertEqual(len(result["availabilities"]), 2)

    def test_many_candidates_still_validate_at_most_three_combinations(self):
        places = [
            place(name, "cafe" if index % 2 == 0 else "culture")
            for index, name in enumerate(("A", "B", "C", "D", "E", "F"))
        ]
        seen = []

        def calculate(request, _):
            seen.append(tuple(item.name for item in request.selected_places))
            return course_result(request)

        recommend_two_place_gacha(
            adventure_request(),
            recommend_places_fn=Mock(return_value=places),
            calculate_course_fn=calculate,
            choice_fn=lambda candidates: candidates[0],
        )
        self.assertGreaterEqual(MAX_COURSE_GACHA_PLACE_CANDIDATES, len(places))
        self.assertEqual(MAX_COURSE_GACHA_VALIDATION_COMBINATIONS, 3)
        self.assertLessEqual(len(seen), 3)

    def test_never_pairs_duplicate_place(self):
        calculate = Mock()
        duplicate = place("A", source_id="same")
        with self.assertRaises(NoAdventureCandidateError):
            recommend_two_place_gacha(
                adventure_request(activities=["cafe"]),
                recommend_places_fn=Mock(return_value=[duplicate, duplicate.copy()]),
                calculate_course_fn=calculate,
            )
        calculate.assert_not_called()

    def test_diverse_activity_is_preferred(self):
        places = [
            place("A", "cafe"),
            place("B", "cafe"),
            place("C", "culture"),
        ]
        result = recommend_two_place_gacha(
            adventure_request(),
            recommend_places_fn=Mock(return_value=places),
            calculate_course_fn=lambda request, _: course_result(request),
            choice_fn=lambda candidates: candidates[0],
        )
        self.assertEqual(
            {item["category"] for item in result["places"]},
            {"cafe", "culture"},
        )

    def test_same_activity_is_fallback_and_single_activity_is_allowed(self):
        places = [place("A"), place("B"), place("C", "culture")]

        def calculate(request, _):
            categories = {item.category for item in request.selected_places}
            if len(categories) > 1:
                return course_result(request, status="INFEASIBLE")
            return course_result(request)

        result = recommend_two_place_gacha(
            adventure_request(),
            recommend_places_fn=Mock(return_value=places),
            calculate_course_fn=calculate,
            choice_fn=lambda candidates: candidates[0],
        )
        self.assertEqual({item["category"] for item in result["places"]}, {"cafe"})

        single = recommend_two_place_gacha(
            adventure_request(activities=["cafe"]),
            recommend_places_fn=Mock(return_value=[place("A"), place("B")]),
            calculate_course_fn=lambda request, _: course_result(request),
            choice_fn=lambda candidates: candidates[0],
        )
        self.assertEqual(len(single["places"]), 2)

    def test_precheck_failure_skips_course_and_does_not_refill(self):
        validate = Mock(return_value={"status": "IMPOSSIBLE_BY_STAY_TIME"})
        calculate = Mock()
        with self.assertRaises(NoAdventureCandidateError):
            recommend_two_place_gacha(
                adventure_request(),
                recommend_places_fn=Mock(return_value=[
                    place("A", "cafe"), place("B", "culture"),
                    place("C", "cafe"), place("D", "culture"),
                ]),
                validate_stay_time_fn=validate,
                calculate_course_fn=calculate,
            )
        self.assertEqual(validate.call_count, 3)
        calculate.assert_not_called()

    def test_infeasible_and_routing_failure_are_excluded(self):
        places = [place("A"), place("B"), place("C")]

        def calculate(request, _):
            names = tuple(item.name for item in request.selected_places)
            if names == ("A", "B"):
                return course_result(request, status="INFEASIBLE")
            if names == ("A", "C"):
                raise HTTPException(status_code=502, detail="routing failed")
            return course_result(request)

        result = recommend_two_place_gacha(
            adventure_request(activities=["cafe"]),
            recommend_places_fn=Mock(return_value=places),
            calculate_course_fn=calculate,
            choice_fn=lambda candidates: candidates[0],
        )
        self.assertEqual({item["name"] for item in result["places"]}, {"B", "C"})

    def test_unexpected_error_is_not_hidden(self):
        with self.assertRaisesRegex(RuntimeError, "bug"):
            recommend_two_place_gacha(
                adventure_request(activities=["cafe"]),
                recommend_places_fn=Mock(return_value=[place("A"), place("B")]),
                calculate_course_fn=Mock(side_effect=RuntimeError("bug")),
            )

    def test_open_pools_are_prioritized_and_choice_runs_once(self):
        places = [place("A"), place("B"), place("C"), place("D")]
        statuses = iter((("unknown", "unknown"), ("open", "unknown"), ("open", "open")))
        choice = Mock(side_effect=lambda candidates: candidates[0])

        result = recommend_two_place_gacha(
            adventure_request(activities=["cafe"]),
            recommend_places_fn=Mock(return_value=places),
            calculate_course_fn=lambda request, _: course_result(request, next(statuses)),
            choice_fn=choice,
        )
        self.assertTrue(result["availability_confirmed"])
        choice.assert_called_once()
        self.assertTrue(all(
            item["status"] == "open"
            for item in choice.call_args.args[0][0]["availabilities"]
        ))

    def test_unknown_fallback_and_closed_statuses(self):
        for blocked_status in (
            "closed", "event_ended", "event_not_started", "not_yet_open"
        ):
            with self.subTest(blocked_status=blocked_status):
                with self.assertRaises(NoAdventureCandidateError):
                    recommend_two_place_gacha(
                        adventure_request(activities=["cafe"]),
                        recommend_places_fn=Mock(return_value=[place("A"), place("B")]),
                        calculate_course_fn=lambda request, _, value=blocked_status: (
                            course_result(request, ("open", value))
                        ),
                    )

        result = recommend_two_place_gacha(
            adventure_request(activities=["cafe"]),
            recommend_places_fn=Mock(return_value=[place("A"), place("B")]),
            calculate_course_fn=lambda request, _: course_result(
                request, ("open", "unknown")
            ),
            choice_fn=lambda candidates: candidates[0],
        )
        self.assertFalse(result["availability_confirmed"])

    def test_preserves_course_order_context_and_index_alignment(self):
        end = {"latitude": 37.6, "longitude": 127.1}
        captured = []

        def calculate(request, _):
            captured.append(request)
            return course_result(request, ("open", "unknown"))

        result = recommend_two_place_gacha(
            adventure_request(
                end_location=end,
                transport_mode="public_transit",
            ),
            recommend_places_fn=Mock(return_value=[
                place("A", "cafe"), place("B", "culture")
            ]),
            calculate_course_fn=calculate,
            choice_fn=lambda candidates: candidates[0],
        )
        request = captured[0]
        self.assertEqual(request.end_location.model_dump(), end)
        self.assertEqual(request.transport_mode, "public_transit")
        self.assertIsNotNone(request.departure_datetime.utcoffset())
        self.assertEqual([item["name"] for item in result["places"]], ["B", "A"])
        self.assertEqual(
            [item["status"] for item in result["availabilities"]],
            ["open", "unknown"],
        )
        validated = CourseCalculationRequest.model_validate(result["course_request"])
        self.assertEqual(len(validated.selected_places), 2)


class AdventureCourseApiTests(unittest.TestCase):
    @patch("adventure_routes.recommend_two_place_gacha")
    def test_endpoint_is_registered(self, recommend_course):
        request = adventure_request()
        recommend_course.return_value = recommend_two_place_gacha(
            request,
            recommend_places_fn=Mock(return_value=[
                place("A", "cafe"), place("B", "culture")
            ]),
            calculate_course_fn=lambda value, _: course_result(value),
            choice_fn=lambda candidates: candidates[0],
        )
        response = client.post(
            "/recommend/adventure/course",
            json=request.model_dump(mode="json"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["places"]), 2)
        CourseCalculationRequest.model_validate(response.json()["course_request"])

    @patch("adventure_routes.recommend_two_place_gacha")
    def test_endpoint_returns_clear_404(self, recommend_course):
        recommend_course.side_effect = NoAdventureCandidateError
        response = client.post(
            "/recommend/adventure/course",
            json=adventure_request().model_dump(mode="json"),
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
