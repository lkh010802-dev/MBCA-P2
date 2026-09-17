import unittest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from adventure_service import create_blind_single_place_gacha
from blind_adventure_cache import (
    BLIND_ADVENTURE_TTL_SECONDS,
    BlindAdventureTokenError,
    clear_blind_adventure_cache,
    get_blind_adventure,
    store_blind_adventure,
)
from main import app
from models import AdventureRequest, AdventureResponse


client = TestClient(app)


def adventure_request():
    return AdventureRequest(
        area={
            "area_name": "성수동",
            "latitude": 37.544,
            "longitude": 127.056,
        },
        recommendation_context={
            "activities": ["cafe"],
            "activity_preferences": {},
            "space_preference": None,
            "transport_mode": "walk",
            "start_location": {"latitude": 37.5, "longitude": 127.0},
            "departure_datetime": "2026-09-14T15:00:00+09:00",
            "end_location": None,
            "available_time_minutes": 120,
        },
    )


def adventure_result():
    arrival = datetime(2026, 9, 14, 15, 10, tzinfo=timezone.utc)
    return {
        "place": {
            "source": "kakao",
            "source_id": "secret-id",
            "name": "비밀 카페",
            "category": "cafe",
            "category_detail": "카페 > 디저트",
            "address": "서울시 비밀로 1",
            "latitude": 37.51,
            "longitude": 127.01,
            "distance_m": 321,
        },
        "availability": {
            "status": "open",
            "arrival_at": arrival,
            "opening_at": None,
            "closing_at": None,
            "remaining_minutes": 90,
        },
        "availability_confirmed": True,
        "course_preview": {
            "status": "FEASIBLE",
            "total_travel_time_minutes": 10,
            "total_stay_time_minutes": 45,
            "total_required_minutes": 55,
            "remaining_time_minutes": 65,
        },
        "course_request": {
            "start_location": {"latitude": 37.5, "longitude": 127.0},
            "selected_places": [{
                "source": "kakao",
                "source_id": "secret-id",
                "name": "비밀 카페",
                "category": "cafe",
                "latitude": 37.51,
                "longitude": 127.01,
            }],
            "available_time_minutes": 120,
            "departure_datetime": "2026-09-14T15:00:00+09:00",
            "end_location": None,
            "transport_mode": "walk",
        },
    }


class BlindAdventureCacheTests(unittest.TestCase):
    def setUp(self):
        clear_blind_adventure_cache()

    def tearDown(self):
        clear_blind_adventure_cache()

    def test_ttl_is_ten_minutes_and_expiry_is_lazy(self):
        token = store_blind_adventure(
            adventure_result(),
            now_fn=lambda: 100.0,
            token_fn=lambda _: "token",
        )

        self.assertEqual(BLIND_ADVENTURE_TTL_SECONDS, 600)
        self.assertEqual(
            get_blind_adventure(token, now_fn=lambda: 699.999)["place"]["name"],
            "비밀 카페",
        )
        with self.assertRaises(BlindAdventureTokenError):
            get_blind_adventure(token, now_fn=lambda: 700.0)
        with self.assertRaises(BlindAdventureTokenError):
            get_blind_adventure(token, now_fn=lambda: 700.0)

    def test_storage_and_reads_are_deep_copied(self):
        original = adventure_result()
        token = store_blind_adventure(
            original,
            now_fn=lambda: 0.0,
            token_fn=lambda _: "token",
        )
        original["place"]["name"] = "변경됨"
        first = get_blind_adventure(token, now_fn=lambda: 1.0)
        first["place"]["name"] = "조회 결과 변경"
        second = get_blind_adventure(token, now_fn=lambda: 2.0)

        self.assertEqual(second["place"]["name"], "비밀 카페")


class BlindAdventureServiceTests(unittest.TestCase):
    def test_generation_calls_existing_single_gacha_once_and_uses_allowlist(self):
        recommend_single = Mock(return_value=adventure_result())
        store = Mock(return_value="opaque-token")

        result = create_blind_single_place_gacha(
            adventure_request(),
            recommend_single_fn=recommend_single,
            store_fn=store,
        )

        recommend_single.assert_called_once_with(adventure_request())
        store.assert_called_once()
        self.assertEqual(set(result), {
            "token",
            "category",
            "availability_confirmed",
            "expires_in_seconds",
        })
        self.assertEqual(result["expires_in_seconds"], 600)
        serialized = repr(result)
        for secret in (
            "비밀 카페",
            "secret-id",
            "서울시 비밀로 1",
            "37.51",
            "127.01",
            "321",
        ):
            self.assertNotIn(secret, serialized)


class BlindAdventureApiTests(unittest.TestCase):
    def setUp(self):
        clear_blind_adventure_cache()

    def tearDown(self):
        clear_blind_adventure_cache()

    def test_generated_token_reveals_the_original_adventure(self):
        recommend_single = Mock(return_value=adventure_result())
        blind = create_blind_single_place_gacha(
            adventure_request(),
            recommend_single_fn=recommend_single,
        )

        response = client.post(
            "/recommend/adventure/blind/reveal",
            json={"token": blind["token"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["place"]["name"], "비밀 카페")
        recommend_single.assert_called_once()

    @patch("adventure_routes.create_blind_single_place_gacha")
    def test_blind_endpoint_returns_only_public_fields(self, create_blind):
        create_blind.return_value = {
            "token": "opaque-token",
            "category": "cafe",
            "availability_confirmed": True,
            "expires_in_seconds": 600,
        }
        response = client.post(
            "/recommend/adventure/blind",
            json=adventure_request().model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {
            "token",
            "category",
            "availability_confirmed",
            "expires_in_seconds",
        })

    def test_reveal_returns_stored_response_repeatedly_without_recalculation(self):
        expected = AdventureResponse.model_validate(adventure_result()).model_dump()
        token = store_blind_adventure(
            expected,
            token_fn=lambda _: "opaque-token",
        )

        with (
            patch("adventure_service.recommend_single_place_gacha") as recommend,
            patch("adventure_service.calculate_course") as calculate_course,
            patch("adventure_service.choice") as random_choice,
        ):
            first = client.post(
                "/recommend/adventure/blind/reveal",
                json={"token": token},
            )
            second = client.post(
                "/recommend/adventure/blind/reveal",
                json={"token": token},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["place"]["name"], "비밀 카페")
        AdventureResponse.model_validate(first.json())
        recommend.assert_not_called()
        calculate_course.assert_not_called()
        random_choice.assert_not_called()

    def test_invalid_and_expired_tokens_return_the_same_404(self):
        invalid = client.post(
            "/recommend/adventure/blind/reveal",
            json={"token": "missing-token"},
        )
        token = store_blind_adventure(
            adventure_result(),
            ttl_seconds=0,
            token_fn=lambda _: "expired-token",
        )
        expired = client.post(
            "/recommend/adventure/blind/reveal",
            json={"token": token},
        )

        expected = {"detail": "유효하지 않거나 만료된 가챠 토큰입니다."}
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(expired.status_code, 404)
        self.assertEqual(invalid.json(), expected)
        self.assertEqual(expired.json(), expected)

        empty = client.post(
            "/recommend/adventure/blind/reveal",
            json={"token": ""},
        )
        self.assertEqual(empty.status_code, 404)
        self.assertEqual(empty.json(), expected)


if __name__ == "__main__":
    unittest.main()
