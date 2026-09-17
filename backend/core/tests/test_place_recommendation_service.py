import unittest
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from place_ranking import calculate_distance_score
from popup_service import PopupDataError
from seoul_culture_service import SeoulCultureAPIError
from place_recommendation_cache import (
    PLACE_PAGE_SIZE,
    PlaceCursorExpiredError,
    PlaceCursorNotFoundError,
    clear_place_recommendation_cache,
    create_place_recommendation_page,
    get_next_place_recommendation_page,
)
from place_recommendation_service import (
    SUPPORTED_PLACE_ACTIVITIES,
    build_personalized_activity_order,
    filter_current_nearby_popup_places,
    filter_walk_kakao_places,
    finalize_recommended_places,
    normalize_tour_places,
    recommend_places,
    resolve_place_activities,
)


def make_place(name: str, category: str, distance_m: int):
    return {
        "source": "kakao",
        "source_id": name,
        "name": name,
        "latitude": 37.5 + distance_m / 10000000,
        "longitude": 126.9 + distance_m / 10000000,
        "category": category,
        "category_detail": category,
        "address": f"{name} 주소",
        "distance_m": distance_m,
    }


def make_kakao_places(count: int, prefix: str = "카페"):
    return [
        {
            "id": f"{prefix}-{index}",
            "place_name": f"{prefix} {index}",
            "x": str(126.9 + index / 10000),
            "y": str(37.5 + index / 10000),
            "category_name": prefix,
            "address_name": f"주소 {index}",
            "distance": str(index * 100),
        }
        for index in range(count)
    ]


class ActivityPolicyTests(unittest.TestCase):

    def test_personalized_activity_order_policy(self):
        cases = [
            (
                ["cafe", "culture", "walk"],
                {"cafe": 5, "culture": 4},
                ["cafe", "culture", "walk"],
            ),
            (
                ["cafe", "culture", "walk"],
                {"cafe": 4, "culture": 5},
                ["culture", "cafe", "walk"],
            ),
            (
                ["cafe", "culture"],
                {"cafe": 5, "culture": 5},
                ["cafe", "culture"],
            ),
            (["cafe", "culture"], None, ["cafe", "culture"]),
            (["cafe", "culture"], {}, ["cafe", "culture"]),
            (
                ["cafe", "culture"],
                {"shopping": 5},
                ["cafe", "culture"],
            ),
            (
                ["cafe", "culture", "walk"],
                {"cafe": 3, "culture": 2, "walk": 1},
                ["cafe", "culture", "walk"],
            ),
            (["cafe"], {"cafe": 5}, ["cafe"]),
        ]

        for activities, preferences, expected in cases:
            with self.subTest(
                activities=activities,
                preferences=preferences,
            ):
                original = activities.copy()
                self.assertEqual(
                    build_personalized_activity_order(
                        activities,
                        preferences,
                    ),
                    expected,
                )
                self.assertEqual(activities, original)

    def test_personalization_changes_only_round_robin_activity_order(self):
        places = [
            make_place("가까운 카페", "cafe", 100),
            make_place("먼 카페", "cafe", 200),
            make_place("가까운 문화", "culture", 100),
            make_place("먼 문화", "culture", 200),
        ]
        original = finalize_recommended_places(
            places,
            ["cafe", "culture"],
        )
        personalized = finalize_recommended_places(
            places,
            build_personalized_activity_order(
                ["cafe", "culture"],
                {"culture": 5},
            ),
        )

        self.assertEqual(
            [place["name"] for place in personalized],
            ["가까운 문화", "가까운 카페", "먼 문화", "먼 카페"],
        )
        self.assertEqual(
            {
                place["name"]: (place["place_score"], place["distance_score"])
                for place in personalized
            },
            {
                place["name"]: (place["place_score"], place["distance_score"])
                for place in original
            },
        )

    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value=None,
    )
    @patch(
        "place_recommendation_service.load_popup_places",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions",
        return_value=[],
    )
    @patch("place_recommendation_service.search_places_by_category")
    def test_source_lookup_order_stays_original_before_personalized_round_robin(
        self,
        mock_search,
        _mock_culture,
        _mock_popup,
        _mock_region,
    ):
        def places_for_category(**kwargs):
            code = kwargs["category_code"]
            return make_kakao_places(
                1,
                "카페" if code == "CE7" else "문화",
            )

        mock_search.side_effect = places_for_category

        result = recommend_places(
            area_name="지역",
            latitude=37.5,
            longitude=126.9,
            activities=["cafe", "culture"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
            activity_preferences={"culture": 5},
        )

        self.assertEqual(
            [call.kwargs["category_code"] for call in mock_search.call_args_list],
            ["CE7", "CT1"],
        )
        self.assertEqual(
            [place["category"] for place in result],
            ["culture", "cafe"],
        )

    def test_single_activity_returns_only_that_activity(self):
        result = finalize_recommended_places(
            [
                make_place("음식점", "food", 100),
                make_place("카페 1", "cafe", 200),
                make_place("카페 2", "cafe", 100),
            ],
            ["cafe"],
        )

        self.assertEqual(
            [place["name"] for place in result],
            ["카페 2", "카페 1"],
        )

    def test_multiple_activities_use_round_robin(self):
        result = finalize_recommended_places(
            [
                make_place("음식 2", "food", 200),
                make_place("카페 1", "cafe", 100),
                make_place("음식 1", "food", 100),
                make_place("카페 2", "cafe", 200),
            ],
            ["food", "cafe"],
        )

        self.assertEqual(
            [place["name"] for place in result],
            ["음식 1", "카페 1", "음식 2", "카페 2"],
        )

    def test_empty_activities_open_supported_provider_activities(self):
        self.assertEqual(
            resolve_place_activities([]),
            SUPPORTED_PLACE_ACTIVITIES,
        )

    def test_activity_without_candidates_is_skipped(self):
        result = finalize_recommended_places(
            [
                make_place("카페 1", "cafe", 100),
                make_place("카페 2", "cafe", 200),
            ],
            ["food", "cafe", "culture"],
        )

        self.assertEqual(
            [place["name"] for place in result],
            ["카페 1", "카페 2"],
        )

    def test_walk_and_drink_are_supported(self):
        self.assertEqual(
            resolve_place_activities(["walk", "drink"]),
            ["walk", "drink"],
        )

    def test_walk_prefers_primary_categories(self):
        places = [
            {"place_name": "산책로", "category_name": "여행 > 관광,명소 > 도보여행"},
            {"place_name": "전망대", "category_name": "여행 > 관광,명소 > 전망대"},
        ]

        self.assertEqual(
            [place["place_name"] for place in filter_walk_kakao_places(places)],
            ["산책로"],
        )

    def test_walk_uses_secondary_categories_only_without_primary(self):
        places = [
            {"place_name": "테마거리", "category_name": "여행 > 관광,명소 > 테마거리"},
            {"place_name": "먹자골목", "category_name": "여행 > 관광,명소 > 테마거리 > 먹자골목"},
        ]

        self.assertEqual(
            [place["place_name"] for place in filter_walk_kakao_places(places)],
            ["테마거리"],
        )

    def test_walk_returns_empty_when_no_allowed_category_exists(self):
        places = [
            {
                "place_name": "눈썰매장",
                "category_name": "스포츠,레저 > 스포츠시설 > 눈썰매장",
            },
            {
                "place_name": "문화유산",
                "category_name": "여행 > 관광,명소 > 문화유산",
            },
        ]

        self.assertEqual(filter_walk_kakao_places(places), [])

    def test_distance_based_score_is_unchanged(self):
        result = finalize_recommended_places(
            [make_place("거리 테스트", "cafe", 1000)],
            ["cafe"],
        )

        self.assertEqual(
            result[0]["place_score"],
            calculate_distance_score(1000),
        )
        self.assertEqual(result[0]["distance_score"], 50.0)

    def test_existing_tour_activity_mapping_is_unchanged(self):
        places = [
            {
                "mapX": "126.9",
                "mapY": "37.5",
                "hubTatsNm": category,
                "hubCtgryMclsNm": category,
            }
            for category in ("문화관광", "레저스포츠", "쇼핑")
        ]

        self.assertEqual(
            [place["category"] for place in normalize_tour_places(places)],
            ["culture", "entertainment", "shopping"],
        )


class PlaceActivityPreferenceRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @staticmethod
    def payload(**overrides):
        payload = {
            "area_name": "지역",
            "latitude": 37.5,
            "longitude": 126.9,
            "activities": ["cafe", "culture"],
        }
        payload.update(overrides)
        return payload

    @patch("place_routes.recommend_places", return_value=[])
    def test_valid_empty_and_omitted_activity_preferences(self, mock_recommend):
        payloads = [
            self.payload(activity_preferences={"cafe": 1, "culture": 5}),
            self.payload(activity_preferences={}),
            self.payload(),
        ]

        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.post("/recommend/places", json=payload)
                self.assertEqual(response.status_code, 200)

        self.assertEqual(
            mock_recommend.call_args_list[0].kwargs["activity_preferences"],
            {"cafe": 1, "culture": 5},
        )
        self.assertEqual(
            mock_recommend.call_args_list[1].kwargs["activity_preferences"],
            {},
        )
        self.assertEqual(
            mock_recommend.call_args_list[2].kwargs["activity_preferences"],
            {},
        )

    @patch("place_routes.recommend_places")
    def test_invalid_activity_preferences_return_422(self, mock_recommend):
        invalid_values = [
            {"cafe": 0},
            {"cafe": 6},
            {"invalid": 5},
        ]

        for activity_preferences in invalid_values:
            with self.subTest(activity_preferences=activity_preferences):
                response = self.client.post(
                    "/recommend/places",
                    json=self.payload(
                        activity_preferences=activity_preferences,
                    ),
                )
                self.assertEqual(response.status_code, 422)

        mock_recommend.assert_not_called()


class PlaceRecommendationCacheTests(unittest.TestCase):

    def setUp(self):
        clear_place_recommendation_cache()

    def tearDown(self):
        clear_place_recommendation_cache()

    def test_first_page_returns_at_most_six_places(self):
        places = [
            make_place(f"카페 {index}", "cafe", index * 100)
            for index in range(10)
        ]
        page = create_place_recommendation_page("지역", places)

        self.assertEqual(len(page.places), PLACE_PAGE_SIZE)
        self.assertTrue(page.has_more)
        self.assertIsNotNone(page.cursor)
        self.assertEqual(page.next_offset, PLACE_PAGE_SIZE)

    def test_round_robin_order_continues_on_next_page(self):
        places = []

        for index in range(7):
            places.extend([
                make_place(f"음식 {index}", "food", index * 100),
                make_place(f"카페 {index}", "cafe", index * 100),
            ])

        ordered = finalize_recommended_places(places, ["food", "cafe"])
        first_page = create_place_recommendation_page("지역", ordered)
        second_page = get_next_place_recommendation_page(
            first_page.cursor,
            first_page.next_offset,
        )

        self.assertEqual(
            [place["name"] for place in first_page.places],
            ["음식 0", "카페 0", "음식 1", "카페 1", "음식 2", "카페 2"],
        )
        self.assertEqual(
            [place["name"] for place in second_page.places],
            ["음식 3", "카페 3", "음식 4", "카페 4", "음식 5", "카페 5"],
        )

    def test_personalized_round_robin_order_continues_from_cache(self):
        places = []
        for index in range(4):
            places.extend([
                make_place(f"카페 {index}", "cafe", index * 100),
                make_place(f"문화 {index}", "culture", index * 100),
            ])

        activity_order = build_personalized_activity_order(
            ["cafe", "culture"],
            {"culture": 5},
        )
        ordered = finalize_recommended_places(places, activity_order)
        first_page = create_place_recommendation_page("지역", ordered)
        second_page = get_next_place_recommendation_page(
            first_page.cursor,
            first_page.next_offset,
        )

        self.assertEqual(
            [place["name"] for place in first_page.places],
            ["문화 0", "카페 0", "문화 1", "카페 1", "문화 2", "카페 2"],
        )
        self.assertEqual(
            [place["name"] for place in second_page.places],
            ["문화 3", "카페 3"],
        )

    def test_places_do_not_repeat_between_pages(self):
        places = [
            make_place(f"장소 {index}", "cafe", index * 100)
            for index in range(8)
        ]
        places.append(places[0].copy())
        ordered = finalize_recommended_places(places, ["cafe"])
        first_page = create_place_recommendation_page("지역", ordered)
        second_page = get_next_place_recommendation_page(
            first_page.cursor,
            first_page.next_offset,
        )
        names = [
            place["name"]
            for place in first_page.places + second_page.places
        ]

        self.assertEqual(len(names), len(set(names)))

    def test_last_page_can_have_fewer_than_six_places(self):
        places = [
            make_place(f"장소 {index}", "cafe", index * 100)
            for index in range(8)
        ]
        first_page = create_place_recommendation_page("지역", places)
        last_page = get_next_place_recommendation_page(
            first_page.cursor,
            first_page.next_offset,
        )

        self.assertEqual(len(last_page.places), 2)
        self.assertFalse(last_page.has_more)
        self.assertEqual(last_page.cursor, first_page.cursor)
        self.assertIsNone(last_page.next_offset)

    def test_same_cursor_and_offset_returns_same_page_on_retry(self):
        places = [
            make_place(f"장소 {index}", "cafe", index * 100)
            for index in range(10)
        ]
        first_page = create_place_recommendation_page("지역", places)
        first_attempt = get_next_place_recommendation_page(
            first_page.cursor,
            first_page.next_offset,
        )
        retry_attempt = get_next_place_recommendation_page(
            first_page.cursor,
            first_page.next_offset,
        )

        self.assertEqual(first_attempt.places, retry_attempt.places)
        self.assertEqual(
            first_attempt.next_offset,
            retry_attempt.next_offset,
        )

    def test_invalid_cursor_is_rejected(self):
        with self.assertRaises(PlaceCursorNotFoundError):
            get_next_place_recommendation_page(
                "invalid-cursor",
                PLACE_PAGE_SIZE,
            )

    def test_expired_cursor_is_rejected(self):
        places = [
            make_place(f"장소 {index}", "cafe", index * 100)
            for index in range(7)
        ]
        page = create_place_recommendation_page(
            "지역",
            places,
            ttl_seconds=-1,
        )

        with self.assertRaises(PlaceCursorExpiredError):
            get_next_place_recommendation_page(
                page.cursor,
                page.next_offset,
            )


class PopupRecommendationTests(unittest.TestCase):

    @staticmethod
    def make_popup(**overrides):
        popup = {
            "source": "popup",
            "source_id": "popup-1",
            "name": "테스트 팝업",
            "latitude": 37.5005,
            "longitude": 126.9005,
            "category": "shopping",
            "category_detail": "패션",
            "address": "서울",
            "distance_m": None,
            "start_at": "2026-09-01",
            "end_at": "2026-09-30",
            "status": "ACTIVE",
            "operation_schedule": [{"opening_time": "10:00"}],
            "description": "설명",
            "image_url": "https://example.com/image.jpg",
        }
        popup.update(overrides)
        return popup

    def test_date_activity_distance_filters_and_status_is_not_trusted(self):
        places = [
            self.make_popup(source_id="active", status="UPCOMING"),
            self.make_popup(source_id="ended", end_at="2026-09-06"),
            self.make_popup(source_id="future", start_at="2026-09-08"),
            self.make_popup(source_id="missing-end", end_at=None),
            self.make_popup(source_id="wrong-category", category="food"),
            self.make_popup(
                source_id="far",
                latitude=37.6,
                longitude=127.0,
            ),
        ]

        result = filter_current_nearby_popup_places(
            places,
            ["shopping"],
            37.5,
            126.9,
            reference_date=date(2026, 9, 7),
        )

        self.assertEqual([place["source_id"] for place in result], ["active"])
        self.assertGreater(result[0]["distance_m"], 0)

    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value=None,
    )
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_keyword",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=[],
    )
    @patch("place_recommendation_service.load_popup_places")
    def test_supported_popup_categories_join_and_metadata_is_preserved(
        self,
        mock_load_popups,
        mock_search_category,
        mock_search_keyword,
        mock_get_exhibitions,
        mock_get_region,
    ):
        for category in (
            "shopping", "culture", "food", "cafe", "entertainment",
        ):
            with self.subTest(category=category):
                mock_load_popups.return_value = [
                    self.make_popup(category=category)
                ]
                result = recommend_places(
                    area_name="테스트 지역",
                    latitude=37.5,
                    longitude=126.9,
                    activities=[category],
                    companions=[],
                    budget_max=None,
                    budget_preference=None,
                    space_preference=None,
                )

                self.assertEqual([place["source"] for place in result], ["popup"])
                self.assertEqual(result[0]["operation_schedule"], [{"opening_time": "10:00"}])
                self.assertEqual(result[0]["description"], "설명")

    @patch("place_recommendation_service.load_popup_places")
    @patch(
        "place_recommendation_service.search_places_by_keyword",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=[],
    )
    def test_walk_and_drink_do_not_load_popups(
        self,
        mock_search_category,
        mock_search_keyword,
        mock_load_popups,
    ):
        for activity in ("walk", "drink"):
            with self.subTest(activity=activity):
                recommend_places(
                    area_name="테스트 지역",
                    latitude=37.5,
                    longitude=126.9,
                    activities=[activity],
                    companions=[],
                    budget_max=None,
                    budget_preference=None,
                    space_preference=None,
                )

        mock_load_popups.assert_not_called()

    @patch(
        "place_recommendation_service.load_popup_places",
        side_effect=PopupDataError("파일 오류"),
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=make_kakao_places(1, prefix="음식"),
    )
    def test_popup_file_error_keeps_existing_recommendations(
        self,
        mock_search_category,
        mock_load_popups,
    ):
        result = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["food"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        self.assertEqual([place["source"] for place in result], ["kakao"])


class NormalAndFallbackFlowTests(unittest.TestCase):

    def setUp(self):
        clear_place_recommendation_cache()
        self.popup_loader_patcher = patch(
            "place_recommendation_service.load_popup_places",
            return_value=[],
        )
        self.popup_loader_patcher.start()

    def tearDown(self):
        self.popup_loader_patcher.stop()
        clear_place_recommendation_cache()

    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value=None,
    )
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_keyword",
        return_value=make_kakao_places(2, prefix="술집"),
    )
    @patch("place_recommendation_service.search_places_by_category")
    def test_empty_activities_collect_all_supported_kakao_categories(
        self,
        mock_search_places,
        mock_search_keyword,
        mock_get_exhibitions,
        mock_get_region,
    ):
        category_prefixes = {
            "FD6": "음식",
            "CE7": "카페",
            "CT1": "문화",
            "AT4": "산책",
        }

        def search_side_effect(**kwargs):
            places = make_kakao_places(
                2,
                prefix=category_prefixes[kwargs["category_code"]],
            )

            if kwargs["category_code"] == "AT4":
                for place in places:
                    place["category_name"] = "여행 > 관광,명소 > 도보여행"

            return places

        mock_search_places.side_effect = search_side_effect
        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=[],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        self.assertEqual(mock_search_places.call_count, 4)
        mock_search_keyword.assert_called_once_with(
            latitude=37.5,
            longitude=126.9,
            query="술집",
            radius=2000,
            size=15,
        )
        self.assertEqual(
            [place["category"] for place in ranked_places],
            [
                "food", "cafe", "walk", "culture", "drink",
                "food", "cafe", "walk", "culture", "drink",
            ],
        )
        mock_get_region.assert_called_once()

    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value=None,
    )
    @patch("place_recommendation_service.search_places_by_keyword")
    @patch("place_recommendation_service.search_places_by_category")
    def test_walk_and_drink_join_existing_round_robin(
        self,
        mock_search_category,
        mock_search_keyword,
        mock_get_region,
    ):
        walk_places = make_kakao_places(2, prefix="산책")
        for place in walk_places:
            place["category_name"] = "여행 > 관광,명소 > 숲"

        mock_search_category.side_effect = lambda **kwargs: (
            make_kakao_places(2, prefix="음식")
            if kwargs["category_code"] == "FD6"
            else walk_places
        )
        mock_search_keyword.return_value = make_kakao_places(2, prefix="술집")

        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["food", "walk", "drink"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        self.assertEqual(
            [place["category"] for place in ranked_places],
            ["food", "walk", "drink", "food", "walk", "drink"],
        )

    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value=None,
    )
    @patch(
        "place_recommendation_service.search_places_by_keyword",
        side_effect=RuntimeError("술집 검색 장애"),
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=make_kakao_places(1, prefix="음식"),
    )
    def test_drink_failure_keeps_other_activity_results(
        self,
        mock_search_category,
        mock_search_keyword,
        mock_get_region,
    ):
        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["food", "drink"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        self.assertEqual(
            [place["category"] for place in ranked_places],
            ["food"],
        )

    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value=None,
    )
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions"
    )
    @patch("place_recommendation_service.search_places_by_category")
    def test_culture_places_join_multi_activity_round_robin(
        self,
        mock_search_places,
        mock_get_exhibitions,
        mock_get_region,
    ):
        mock_search_places.side_effect = lambda **kwargs: (
            make_kakao_places(2, prefix="음식")
            if kwargs["category_code"] == "FD6"
            else []
        )
        mock_get_exhibitions.return_value = [
            make_place("전시 1", "culture", 100),
            make_place("전시 2", "culture", 200),
        ]

        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["food", "culture"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        self.assertEqual(
            [place["category"] for place in ranked_places],
            ["food", "culture", "food", "culture"],
        )
        mock_get_exhibitions.assert_called_once_with(
            latitude=37.5,
            longitude=126.9,
            max_distance_m=2000,
        )

    @patch("place_recommendation_service.get_latest_hub_places")
    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value={"sigungu_name": "마포구"},
    )
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions",
        side_effect=SeoulCultureAPIError("장애"),
    )
    @patch("place_recommendation_service.search_places_by_category")
    def test_culture_api_failure_keeps_kakao_and_tour_results(
        self,
        mock_search_places,
        mock_get_exhibitions,
        mock_get_region,
        mock_get_latest_hub_places,
    ):
        mock_search_places.return_value = make_kakao_places(1, prefix="문화")
        mock_get_latest_hub_places.return_value = [{
            "mapX": "126.9",
            "mapY": "37.5",
            "hubTatsNm": "Tour 문화",
            "hubCtgryMclsNm": "문화관광",
            "hubRank": "1",
        }]

        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["culture"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        self.assertEqual(
            {place["source"] for place in ranked_places},
            {"kakao", "tour"},
        )

    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        side_effect=RuntimeError("지역 API 장애"),
    )
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions",
        return_value=[make_place("현재 전시", "culture", 100)],
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=[],
    )
    def test_tour_fallback_keeps_culture_results(
        self,
        mock_search_places,
        mock_get_exhibitions,
        mock_get_region,
    ):
        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["culture"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        self.assertEqual(
            [place["name"] for place in ranked_places],
            ["현재 전시"],
        )

    @patch("place_recommendation_service.get_latest_hub_places")
    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value={"sigungu_name": "마포구"},
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=make_kakao_places(1, prefix="음식"),
    )
    def test_non_tour_activity_skips_tour_and_keeps_kakao_results(
        self,
        mock_search_places,
        mock_get_region,
        mock_get_latest_hub_places,
    ):
        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["food"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        self.assertEqual(
            [place["category"] for place in ranked_places],
            ["food"],
        )
        mock_get_region.assert_not_called()
        mock_get_latest_hub_places.assert_not_called()

    @patch("place_recommendation_service.get_latest_hub_places")
    @patch("place_recommendation_service.get_region_from_coordinates")
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_keyword",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=[],
    )
    def test_each_non_tour_activity_skips_tour_path(
        self,
        mock_search_category,
        mock_search_keyword,
        mock_get_exhibitions,
        mock_get_region,
        mock_get_latest_hub_places,
    ):
        for activity in ("food", "cafe", "walk", "drink"):
            with self.subTest(activity=activity):
                recommend_places(
                    area_name="테스트 지역",
                    latitude=37.5,
                    longitude=126.9,
                    activities=[activity],
                    companions=[],
                    budget_max=None,
                    budget_preference=None,
                    space_preference=None,
                )

        mock_get_region.assert_not_called()
        mock_get_latest_hub_places.assert_not_called()

    @patch("place_recommendation_service.get_latest_hub_places")
    @patch("place_recommendation_service.get_region_from_coordinates")
    @patch(
        "place_recommendation_service.search_places_by_keyword",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=[],
    )
    def test_non_tour_activity_mix_skips_tour_path(
        self,
        mock_search_category,
        mock_search_keyword,
        mock_get_region,
        mock_get_latest_hub_places,
    ):
        recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["food", "cafe", "walk", "drink"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        mock_get_region.assert_not_called()
        mock_get_latest_hub_places.assert_not_called()

    @patch(
        "place_recommendation_service.get_latest_hub_places",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value={"sigungu_name": "마포구"},
    )
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=[],
    )
    def test_each_tour_activity_enters_tour_path(
        self,
        mock_search_category,
        mock_get_exhibitions,
        mock_get_region,
        mock_get_latest_hub_places,
    ):
        for activity in ("culture", "entertainment", "shopping"):
            with self.subTest(activity=activity):
                recommend_places(
                    area_name="테스트 지역",
                    latitude=37.5,
                    longitude=126.9,
                    activities=[activity],
                    companions=[],
                    budget_max=None,
                    budget_preference=None,
                    space_preference=None,
                )

        self.assertEqual(mock_get_region.call_count, 3)
        self.assertEqual(mock_get_latest_hub_places.call_count, 3)

    @patch(
        "place_recommendation_service.get_latest_hub_places",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value={"sigungu_name": "마포구"},
    )
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=[],
    )
    def test_mixed_tour_and_non_tour_activities_enter_tour_path(
        self,
        mock_search_category,
        mock_get_exhibitions,
        mock_get_region,
        mock_get_latest_hub_places,
    ):
        recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["food", "culture"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        mock_get_region.assert_called_once()
        mock_get_latest_hub_places.assert_called_once()

    @patch(
        "place_recommendation_service.get_latest_hub_places",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value={"sigungu_name": "마포구"},
    )
    @patch(
        "place_recommendation_service.get_nearby_current_exhibitions",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_keyword",
        return_value=[],
    )
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=[],
    )
    def test_empty_activities_enter_tour_path(
        self,
        mock_search_category,
        mock_search_keyword,
        mock_get_exhibitions,
        mock_get_region,
        mock_get_latest_hub_places,
    ):
        recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=[],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        mock_get_region.assert_called_once()
        mock_get_latest_hub_places.assert_called_once()

    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value=None,
    )
    @patch("place_recommendation_service.get_nearby_current_exhibitions")
    @patch(
        "place_recommendation_service.search_places_by_category",
        return_value=[],
    )
    def test_non_culture_does_not_call_culture_api(
        self,
        mock_search_places,
        mock_get_exhibitions,
        mock_get_region,
    ):
        recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["cafe"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )

        mock_get_exhibitions.assert_not_called()

    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value=None,
    )
    @patch("place_recommendation_service.search_places_by_category")
    def test_fallback_uses_same_pagination_policy(
        self,
        mock_search_places,
        mock_get_region,
    ):
        mock_search_places.return_value = make_kakao_places(8)
        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["cafe"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )
        page = create_place_recommendation_page("테스트 지역", ranked_places)

        self.assertEqual(len(page.places), 6)
        self.assertTrue(page.has_more)
        mock_get_region.assert_not_called()

    @patch("place_recommendation_service.get_latest_hub_places")
    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value={"sigungu_name": "마포구"},
    )
    @patch("place_recommendation_service.search_places_by_category")
    def test_normal_path_uses_same_pagination_policy(
        self,
        mock_search_places,
        mock_get_region,
        mock_get_latest_hub_places,
    ):
        mock_search_places.return_value = make_kakao_places(8)
        mock_get_latest_hub_places.return_value = [
            {
                "mapX": "126.9",
                "mapY": "37.5",
                "hubTatsNm": "문화 장소",
                "hubCtgryMclsNm": "문화관광",
                "hubRank": "1",
            }
        ]
        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["cafe"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )
        page = create_place_recommendation_page("테스트 지역", ranked_places)

        self.assertEqual(len(page.places), 6)
        self.assertTrue(page.has_more)
        mock_get_region.assert_not_called()
        mock_get_latest_hub_places.assert_not_called()

    @patch("place_recommendation_service.get_latest_hub_places")
    @patch(
        "place_recommendation_service.get_region_from_coordinates",
        return_value=None,
    )
    @patch("place_recommendation_service.search_places_by_category")
    def test_next_page_does_not_call_external_apis_again(
        self,
        mock_search_places,
        mock_get_region,
        mock_get_latest_hub_places,
    ):
        mock_search_places.return_value = make_kakao_places(8)
        ranked_places = recommend_places(
            area_name="테스트 지역",
            latitude=37.5,
            longitude=126.9,
            activities=["cafe"],
            companions=[],
            budget_max=None,
            budget_preference=None,
            space_preference=None,
        )
        first_page = create_place_recommendation_page(
            "테스트 지역",
            ranked_places,
        )
        search_call_count = mock_search_places.call_count
        region_call_count = mock_get_region.call_count

        get_next_place_recommendation_page(
            first_page.cursor,
            first_page.next_offset,
        )

        self.assertEqual(mock_search_places.call_count, search_call_count)
        self.assertEqual(mock_get_region.call_count, region_call_count)
        mock_get_latest_hub_places.assert_not_called()


if __name__ == "__main__":
    unittest.main()
