import unittest
from unittest.mock import patch

from place_recommendation_cache import (
    clear_place_recommendation_cache,
    create_place_recommendation_page,
    get_next_place_recommendation_page,
)
from place_recommendation_service import (
    finalize_recommended_places,
    recommend_places,
)
from place_ranking import calculate_place_score
from place_space import classify_place_space


UNKNOWN = {
    "space_type": "unknown",
    "space_type_confidence": "unknown",
    "space_type_basis": "unknown",
}


class PlaceSpaceRankingTests(unittest.TestCase):
    def test_space_preference_bonuses(self):
        cases = [
            ("indoor", "indoor", "high", 2.0),
            ("indoor", "indoor", "medium", 1.0),
            ("indoor", "mixed", "high", 0.5),
            ("indoor", "outdoor", "high", 0),
            ("indoor", "unknown", "unknown", 0),
            ("outdoor", "outdoor", "high", 2.0),
            ("outdoor", "outdoor", "medium", 1.0),
            ("outdoor", "mixed", "high", 0.5),
            ("outdoor", "indoor", "high", 0),
        ]

        for preference, space_type, confidence, bonus in cases:
            with self.subTest(
                preference=preference,
                space_type=space_type,
                confidence=confidence,
            ):
                place = {
                    "distance_m": 1000,
                    "space_type": space_type,
                    "space_type_confidence": confidence,
                }
                self.assertEqual(
                    calculate_place_score(place, preference),
                    50.0 + bonus,
                )

    def test_any_none_and_missing_distance_do_not_apply_bonus(self):
        place = {
            "distance_m": 1000,
            "space_type": "indoor",
            "space_type_confidence": "high",
        }

        self.assertEqual(calculate_place_score(place, "any"), 50.0)
        self.assertEqual(calculate_place_score(place, None), 50.0)
        self.assertEqual(
            calculate_place_score(place | {"distance_m": None}, "indoor"),
            0,
        )
        self.assertEqual(
            calculate_place_score(place | {"distance_m": 0}, "indoor"),
            102.0,
        )

    def test_small_preference_bonus_can_only_reverse_nearby_places(self):
        nearby_unknown = {
            "distance_m": 100,
            "space_type": "unknown",
            "space_type_confidence": "unknown",
        }
        slightly_farther_indoor = {
            "distance_m": 130,
            "space_type": "indoor",
            "space_type_confidence": "high",
        }
        much_farther_indoor = slightly_farther_indoor | {"distance_m": 200}

        self.assertGreater(
            calculate_place_score(slightly_farther_indoor, "indoor"),
            calculate_place_score(nearby_unknown, "indoor"),
        )
        self.assertLess(
            calculate_place_score(much_farther_indoor, "indoor"),
            calculate_place_score(nearby_unknown, "indoor"),
        )


class PlaceSpaceClassifierTests(unittest.TestCase):
    def test_popup_explicit_indoor(self):
        result = classify_place_space({
            "source": "popup",
            "popup_categories": ["패션", "실내 팝업"],
        })

        self.assertEqual(result, {
            "space_type": "indoor",
            "space_type_confidence": "high",
            "space_type_basis": "explicit",
        })

    def test_explicit_outdoor_square(self):
        result = classify_place_space({
            "source": "popup",
            "venue_name": "DDP 야외광장",
        })

        self.assertEqual(result, {
            "space_type": "outdoor",
            "space_type_confidence": "high",
            "space_type_basis": "explicit",
        })

    def test_directly_expressed_mixed_space(self):
        result = classify_place_space({
            "source": "seoul_culture",
            "description": "실내외 복합 행사입니다.",
        })

        self.assertEqual(result, {
            "space_type": "mixed",
            "space_type_confidence": "high",
            "space_type_basis": "explicit",
        })

    def test_conflicting_explicit_evidence_is_unknown(self):
        result = classify_place_space({
            "source": "popup",
            "popup_categories": ["실내 팝업"],
            "venue_name": "야외 공간",
        })

        self.assertEqual(result, UNKNOWN)

    def test_kakao_exact_walking_category_is_outdoor(self):
        result = classify_place_space({
            "source": "kakao",
            "category_detail": "여행 > 관광,명소 > 도보여행",
        })

        self.assertEqual(result, {
            "space_type": "outdoor",
            "space_type_confidence": "medium",
            "space_type_basis": "category",
        })

    def test_kakao_exact_museum_category_is_indoor(self):
        result = classify_place_space({
            "source": "kakao",
            "category_detail": "문화시설 > 박물관",
        })

        self.assertEqual(result, {
            "space_type": "indoor",
            "space_type_confidence": "medium",
            "space_type_basis": "category",
        })

    def test_seoul_culture_museum_venue_is_indoor(self):
        result = classify_place_space({
            "source": "seoul_culture",
            "venue_name": "테스트 미술관",
        })

        self.assertEqual(result, {
            "space_type": "indoor",
            "space_type_confidence": "medium",
            "space_type_basis": "venue",
        })

    def test_broad_tour_category_is_unknown(self):
        self.assertEqual(
            classify_place_space({
                "source": "tour",
                "category_detail": "쇼핑",
            }),
            UNKNOWN,
        )

    def test_activity_alone_does_not_determine_space(self):
        for category in ("food", "cafe", "shopping", "culture", "walk"):
            with self.subTest(category=category):
                self.assertEqual(
                    classify_place_space({
                        "source": "kakao",
                        "category": category,
                    }),
                    UNKNOWN,
                )

    def test_dangerous_substrings_are_unknown(self):
        cases = [
            {"source": "kakao", "category_detail": "문화유산"},
            {"source": "popup", "address": "서울숲길 10"},
            {"source": "popup", "venue_name": "정원식당"},
            {"source": "popup", "venue_name": "공원 앞 카페"},
            {"source": "popup", "venue_name": "테스트 센터"},
            {"source": "popup", "venue_name": "테스트 스퀘어"},
        ]

        for place in cases:
            with self.subTest(place=place):
                self.assertEqual(classify_place_space(place), UNKNOWN)

    def test_missing_information_is_unknown(self):
        self.assertEqual(classify_place_space({}), UNKNOWN)

    def test_input_place_is_not_modified(self):
        place = {
            "source": "popup",
            "popup_categories": ["실내 팝업"],
        }
        original = {
            "source": "popup",
            "popup_categories": ["실내 팝업"],
        }

        classify_place_space(place)

        self.assertEqual(place, original)


class PlaceSpaceIntegrationTests(unittest.TestCase):
    def tearDown(self):
        clear_place_recommendation_cache()

    @staticmethod
    def place(name, distance_m, **extra):
        return {
            "source": "kakao",
            "source_id": name,
            "name": name,
            "latitude": 37.5,
            "longitude": 126.9,
            "category": "culture",
            "category_detail": "문화시설",
            "address": "주소",
            "distance_m": distance_m,
        } | extra

    def test_finalize_adds_metadata_without_changing_score_or_order(self):
        result = finalize_recommended_places(
            [
                self.place("먼 박물관", 1000, category_detail="문화시설 > 박물관"),
                self.place("가까운 장소", 100),
            ],
            ["culture"],
        )

        self.assertEqual(
            [place["name"] for place in result],
            ["가까운 장소", "먼 박물관"],
        )
        self.assertEqual(
            [place["place_score"] for place in result],
            [95.0, 50.0],
        )
        self.assertEqual(result[0]["space_type"], "unknown")
        self.assertEqual(result[1]["space_type"], "indoor")

    def test_space_preference_keeps_activity_round_robin(self):
        result = finalize_recommended_places(
            [
                self.place("가까운 문화", 100),
                self.place(
                    "선호 문화",
                    130,
                    category_detail="문화시설 > 박물관",
                ),
                self.place("가까운 카페", 100, category="cafe"),
                self.place(
                    "선호 카페",
                    130,
                    category="cafe",
                    source="popup",
                    popup_categories=["실내 팝업"],
                ),
            ],
            ["culture", "cafe"],
            "indoor",
        )

        self.assertEqual(
            [place["name"] for place in result],
            ["가까운 문화", "선호 카페", "선호 문화", "가까운 카페"],
        )

    def test_tour_fallback_result_keeps_space_metadata(self):
        kakao_place = {
            "id": "museum",
            "place_name": "테스트 박물관",
            "x": "126.9",
            "y": "37.5",
            "category_name": "문화시설 > 박물관",
            "address_name": "주소",
            "distance": "100",
        }

        with (
            patch(
                "place_recommendation_service.search_places_by_category",
                return_value=[kakao_place],
            ),
            patch(
                "place_recommendation_service.get_nearby_current_exhibitions",
                return_value=[],
            ),
            patch(
                "place_recommendation_service.load_popup_places",
                return_value=[],
            ),
            patch(
                "place_recommendation_service.get_region_from_coordinates",
                return_value=None,
            ),
        ):
            result = recommend_places(
                area_name="지역",
                latitude=37.5,
                longitude=126.9,
                activities=["culture"],
                companions=[],
                budget_max=None,
                budget_preference=None,
                space_preference="indoor",
            )

        self.assertEqual(result[0]["space_type"], "indoor")
        self.assertEqual(result[0]["space_type_basis"], "category")
        self.assertEqual(result[0]["distance_score"], 95.0)
        self.assertEqual(result[0]["place_score"], 96.0)

    def test_cached_pages_keep_metadata_without_reclassification(self):
        places = [
            self.place(f"장소 {index}", index * 100)
            for index in range(8)
        ]

        with patch(
            "place_recommendation_service.classify_place_space",
            wraps=classify_place_space,
        ) as mock_classify:
            ranked = finalize_recommended_places(
                places,
                ["culture"],
                "indoor",
            )
            first_page = create_place_recommendation_page("지역", ranked)
            calls_after_creation = mock_classify.call_count
            next_page = get_next_place_recommendation_page(
                first_page.cursor,
                first_page.next_offset,
            )

        self.assertEqual(calls_after_creation, len(places))
        self.assertEqual(mock_classify.call_count, calls_after_creation)
        self.assertTrue(all(
            "space_type" in place
            for place in first_page.places + next_page.places
        ))
        self.assertEqual(
            next_page.places,
            ranked[len(first_page.places):],
        )


if __name__ == "__main__":
    unittest.main()
