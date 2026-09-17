import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from adventure_service import create_blind_two_place_gacha
from blind_adventure_cache import (
    clear_blind_adventure_cache,
    store_blind_adventure,
)
from main import app
from models import AdventureCourseResponse, AdventureRequest


client = TestClient(app)


def adventure_request():
    return AdventureRequest(
        area={
            "area_name": "성수동",
            "latitude": 37.544,
            "longitude": 127.056,
        },
        recommendation_context={
            "activities": ["cafe", "culture"],
            "activity_preferences": {},
            "space_preference": None,
            "transport_mode": "walk",
            "start_location": {"latitude": 37.5, "longitude": 127.0},
            "departure_datetime": "2026-09-14T15:00:00+09:00",
            "end_location": None,
            "available_time_minutes": 180,
        },
    )


def adventure_course_result():
    arrival = datetime(2026, 9, 14, 15, 10, tzinfo=timezone.utc)
    places = [
        {
            "source": "kakao",
            "source_id": "secret-cafe",
            "name": "비밀 카페",
            "category": "cafe",
            "address": "서울시 비밀로 1",
            "latitude": 37.51,
            "longitude": 127.01,
        },
        {
            "source": "seoul_culture",
            "source_id": "secret-gallery",
            "name": "비밀 전시",
            "category": "culture",
            "address": "서울시 비밀로 2",
            "latitude": 37.52,
            "longitude": 127.02,
        },
    ]
    availability = {
        "status": "open",
        "arrival_at": arrival,
        "opening_at": None,
        "closing_at": None,
        "remaining_minutes": 90,
    }
    return {
        "places": places,
        "availabilities": [availability, availability],
        "availability_confirmed": True,
        "course_preview": {
            "status": "FEASIBLE",
            "total_travel_time_minutes": 30,
            "total_stay_time_minutes": 120,
            "total_required_minutes": 150,
            "remaining_time_minutes": 30,
        },
        "course_request": {
            "start_location": {"latitude": 37.5, "longitude": 127.0},
            "selected_places": places,
            "available_time_minutes": 180,
            "departure_datetime": "2026-09-14T15:00:00+09:00",
            "end_location": None,
            "transport_mode": "walk",
        },
    }


class BlindAdventureCourseTests(unittest.TestCase):
    def setUp(self):
        clear_blind_adventure_cache()

    def tearDown(self):
        clear_blind_adventure_cache()

    def test_generation_calls_existing_course_gacha_once_and_hides_places(self):
        recommend_course = Mock(return_value=adventure_course_result())
        store = Mock(return_value="opaque-token")

        result = create_blind_two_place_gacha(
            adventure_request(),
            recommend_course_fn=recommend_course,
            store_fn=store,
        )

        recommend_course.assert_called_once_with(adventure_request())
        store.assert_called_once()
        self.assertEqual(store.call_args.kwargs, {"kind": "course"})
        self.assertEqual(set(result), {
            "token",
            "place_count",
            "activities",
            "availability_confirmed",
            "expires_in_seconds",
        })
        self.assertEqual(result["place_count"], 2)
        self.assertEqual(result["expires_in_seconds"], 600)
        serialized = repr(result)
        for secret in (
            "비밀 카페",
            "비밀 전시",
            "secret-cafe",
            "secret-gallery",
            "서울시 비밀로",
            "37.51",
            "127.01",
        ):
            self.assertNotIn(secret, serialized)

    def test_reveal_returns_same_stored_course_without_recommendation(self):
        expected = AdventureCourseResponse.model_validate(
            adventure_course_result()
        ).model_dump()
        token = store_blind_adventure(
            expected,
            kind="course",
            token_fn=lambda _: "opaque-token",
        )

        with (
            patch("adventure_service.recommend_two_place_gacha") as recommend,
            patch("adventure_service.calculate_course") as calculate_course,
            patch("adventure_service.choice") as random_choice,
        ):
            first = client.post(
                "/recommend/adventure/blind/course/reveal",
                json={"token": token},
            )
            second = client.post(
                "/recommend/adventure/blind/course/reveal",
                json={"token": token},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(
            [place["name"] for place in first.json()["places"]],
            ["비밀 카페", "비밀 전시"],
        )
        AdventureCourseResponse.model_validate(first.json())
        recommend.assert_not_called()
        calculate_course.assert_not_called()
        random_choice.assert_not_called()

    @patch("adventure_routes.create_blind_two_place_gacha")
    def test_generation_endpoint_returns_only_allowlisted_fields(self, create):
        create.return_value = {
            "token": "opaque-token",
            "place_count": 2,
            "activities": ["cafe", "culture"],
            "availability_confirmed": True,
            "expires_in_seconds": 600,
        }

        response = client.post(
            "/recommend/adventure/blind/course",
            json=adventure_request().model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {
            "token",
            "place_count",
            "activities",
            "availability_confirmed",
            "expires_in_seconds",
        })

    def test_invalid_and_expired_tokens_share_the_existing_404_contract(self):
        invalid = client.post(
            "/recommend/adventure/blind/course/reveal",
            json={"token": "missing-token"},
        )
        token = store_blind_adventure(
            adventure_course_result(),
            ttl_seconds=0,
            kind="course",
            token_fn=lambda _: "expired-token",
        )
        expired = client.post(
            "/recommend/adventure/blind/course/reveal",
            json={"token": token},
        )

        expected = {"detail": "유효하지 않거나 만료된 가챠 토큰입니다."}
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(expired.status_code, 404)
        self.assertEqual(invalid.json(), expected)
        self.assertEqual(expired.json(), expected)

    def test_single_token_is_invalid_for_course_reveal(self):
        token = store_blind_adventure(
            {"place": {"name": "single"}},
            token_fn=lambda _: "single-token",
        )

        response = client.post(
            "/recommend/adventure/blind/course/reveal",
            json={"token": token},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "유효하지 않거나 만료된 가챠 토큰입니다."},
        )


if __name__ == "__main__":
    unittest.main()
