import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from adventure_service import recommend_seoul_gacha
from main import app
from models import PlaceRecommendRequest, SeoulGachaRequest


client = TestClient(app)


def area(name, latitude, longitude, **extra):
    return {
        "AREA_NM": name,
        "latitude": latitude,
        "longitude": longitude,
        **extra,
    }


def seoul_gacha_request(**overrides):
    payload = {
        "target_area": None,
        "current_area": area("성수동", 37.544, 127.056),
        "other_areas": [area("서울숲", 37.545, 127.04)],
        "extended_areas": [area("건대입구", 37.54, 127.07)],
        "recommendation_context": {
            "activities": ["cafe"],
            "activity_preferences": {"cafe": 5},
            "space_preference": "indoor",
            "transport_mode": "walk",
            "start_location": {"latitude": 37.5, "longitude": 127.0},
            "departure_datetime": "2026-09-14T15:00:00+09:00",
            "end_location": None,
            "end_datetime": None,
            "available_time_minutes": 120,
        },
    }
    payload.update(overrides)
    return SeoulGachaRequest.model_validate(payload)


class SeoulGachaServiceTests(unittest.TestCase):
    def test_target_area_is_selected_without_random_choice(self):
        target = area("종로", 37.57, 126.98)
        choice_fn = Mock()

        result = recommend_seoul_gacha(
            seoul_gacha_request(target_area=target),
            choice_fn=choice_fn,
        )

        self.assertEqual(result["selected_area"].AREA_NM, "종로")
        self.assertEqual(result["selection_source"], "target")
        choice_fn.assert_not_called()

    def test_current_and_other_areas_form_ordered_equal_choice_pool(self):
        choice_fn = Mock(side_effect=lambda candidates: candidates[-1])
        request = seoul_gacha_request(
            current_area=area("성수동", 37.544, 127.056, final_score=1),
            other_areas=[
                area("서울숲", 37.545, 127.04, final_score=999),
            ],
        )

        result = recommend_seoul_gacha(request, choice_fn=choice_fn)

        pool = choice_fn.call_args.args[0]
        self.assertEqual([item.AREA_NM for item in pool], ["성수동", "서울숲"])
        self.assertEqual(result["selected_area"].AREA_NM, "서울숲")
        self.assertEqual(result["selection_source"], "recommended")

    def test_other_areas_work_without_current_area_and_duplicates_are_removed(self):
        duplicate = area("서울숲", 37.545, 127.04)
        choice_fn = Mock(side_effect=lambda candidates: candidates[0])

        result = recommend_seoul_gacha(
            seoul_gacha_request(
                current_area=None,
                other_areas=[duplicate, duplicate],
            ),
            choice_fn=choice_fn,
        )

        self.assertEqual(len(choice_fn.call_args.args[0]), 1)
        self.assertEqual(result["selected_area"].AREA_NM, "서울숲")

    def test_extended_areas_are_used_only_as_fallback(self):
        result = recommend_seoul_gacha(
            seoul_gacha_request(current_area=None, other_areas=[]),
            choice_fn=lambda candidates: candidates[0],
        )

        self.assertEqual(result["selected_area"].AREA_NM, "건대입구")
        self.assertEqual(result["selection_source"], "extended")

    def test_null_available_time_preserves_context_and_builds_place_request(self):
        request = seoul_gacha_request(
            recommendation_context={
                **seoul_gacha_request().recommendation_context.model_dump(),
                "available_time_minutes": None,
            }
        )

        result = recommend_seoul_gacha(
            request,
            choice_fn=lambda candidates: candidates[0],
        )

        self.assertIsNone(result["recommendation_context"].available_time_minutes)
        place_request = PlaceRecommendRequest.model_validate(
            result["place_request"]
        )
        self.assertEqual(place_request.area_name, "성수동")
        self.assertEqual(place_request.activities, ["cafe"])
        self.assertEqual(place_request.activity_preferences, {"cafe": 5})

    def test_does_not_call_place_or_congestion_services(self):
        with (
            patch("adventure_service.recommend_places") as recommend_places,
            patch("congestion_service.get_congestion_data") as congestion,
        ):
            recommend_seoul_gacha(
                seoul_gacha_request(),
                choice_fn=lambda candidates: candidates[0],
            )

        recommend_places.assert_not_called()
        congestion.assert_not_called()


class SeoulGachaApiTests(unittest.TestCase):
    def test_endpoint_returns_ready_to_send_place_request(self):
        response = client.post(
            "/recommend/adventure/seoul",
            json=seoul_gacha_request().model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        PlaceRecommendRequest.model_validate(body["place_request"])
        self.assertIn(body["selection_source"], {"recommended", "extended"})
        self.assertEqual(
            body["recommendation_context"],
            seoul_gacha_request().model_dump(mode="json")[
                "recommendation_context"
            ],
        )

    def test_empty_candidate_pools_return_domain_404(self):
        request = seoul_gacha_request(
            current_area=None,
            other_areas=[],
            extended_areas=[],
        )

        response = client.post(
            "/recommend/adventure/seoul",
            json=request.model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "현재 조건에서 선택 가능한 서울 추천 지역이 없습니다.",
        )


if __name__ == "__main__":
    unittest.main()
