import unittest

from integration.classifier import classify_popply


class ClassificationRegression20260908(unittest.TestCase):

    def test_popply_original_art_exhibition_is_non_popup(self):
        row = {
            "source": "popply",
            "name": "⟪이기훈 원화전: 내일의 낙원⟫",
            "description": "한국 작가 이기훈의 대규모 원화전",
            "category": "카테고리 없음",
            "start_date": "2026-07-17",
            "end_date": "2026-11-29",
            "tags": ["원화전", "전시"],
            "source_record_raw": {
                "category_raw": "전시",
                "event_type_raw": "카테고리 없음",
            },
        }

        result = classify_popply(row)

        self.assertEqual("NON_POPUP", result["classification"])
        self.assertEqual(
            "cultural_event_title_or_category",
            result["classification_reasons"][0],
        )

    def test_popply_museum_exhibition_is_non_popup(self):
        row = {
            "source": "popply",
            "name": "《유영국: 산은 내 안에 있다》",
            "description": "서울시립미술관에서 열리는 작가 전시",
            "category": "카테고리 없음",
            "start_date": "2026-05-19",
            "end_date": "2026-10-25",
            "tags": ["서울시립미술관", "전시회"],
            "source_record_raw": {
                "category_raw": "전시",
                "event_type_raw": "카테고리 없음",
            },
        }

        result = classify_popply(row)

        self.assertEqual("NON_POPUP", result["classification"])

    def test_short_brand_commerce_event_is_popup(self):
        row = {
            "source": "popply",
            "name": "할머니 옷장 안의 100년된 신상",
            "description": (
                "13개의 브랜드가 참여하며 오래 사용할 물건을 "
                "직접 보고 마음에 드는 물건을 고를 수 있습니다."
            ),
            "category": "브랜드/캠페인",
            "start_date": "2026-09-18",
            "end_date": "2026-09-20",
            "tags": ["전통", "브랜드", "리빙", "랜덤박스"],
            "source_record_raw": {
                "category_raw": "브랜드/캠페인",
            },
        }

        result = classify_popply(row)

        self.assertEqual("POPUP", result["classification"])
        self.assertEqual(
            "short_brand_commerce_event",
            result["classification_reasons"][0],
        )

    def test_explicit_popup_still_wins_over_exhibition_category(self):
        row = {
            "source": "popply",
            "name": "브랜드 전시 팝업",
            "description": "",
            "category": "카테고리 없음",
            "start_date": "2026-09-01",
            "end_date": "2026-09-10",
            "tags": [],
            "source_record_raw": {
                "category_raw": "전시",
            },
        }

        result = classify_popply(row)

        self.assertEqual("POPUP", result["classification"])

    def test_long_brand_campaign_is_not_forced_to_popup(self):
        row = {
            "source": "popply",
            "name": "브랜드 캠페인",
            "description": "브랜드 제품을 소개합니다.",
            "category": "브랜드/캠페인",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "tags": ["브랜드"],
            "source_record_raw": {
                "category_raw": "브랜드/캠페인",
            },
        }

        result = classify_popply(row)

        self.assertNotEqual("short_brand_commerce_event",
                            result["classification_reasons"][0])


if __name__ == "__main__":
    unittest.main()
