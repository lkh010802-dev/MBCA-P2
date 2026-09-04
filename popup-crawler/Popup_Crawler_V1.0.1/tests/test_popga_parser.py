from __future__ import annotations

import unittest

from crawlers.popga import LIST_URL, parse_card_blocks, parse_list_lines


class PopgaParserTests(unittest.TestCase):
    def test_list_url_has_explicit_seoul_filter(self) -> None:
        self.assertIn("areaCodes%5B0%5D=1100000000", LIST_URL)

    def test_card_block_preserves_detail_id_and_raw_values(self) -> None:
        rows = parse_card_blocks([
            {
                "detail_url": "https://popga.co.kr/popup/8366?from=list",
                "card_text": (
                    "찜하기\n운영중\n소녀시대 19주년 팝업\n성수\n"
                    "26. 08. 05 - 26. 08. 07\n연예인/셀럽"
                ),
            }
        ])

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("8366", row.source_id)
        self.assertEqual("소녀시대 19주년 팝업", row.name_raw)
        self.assertEqual("성수", row.area_raw)
        self.assertEqual("26. 08. 05 - 26. 08. 07", row.period_raw)
        self.assertEqual("2026-08-05", row.start_date)
        self.assertEqual("2026-08-07", row.end_date)
        self.assertEqual("연예인/셀럽", row.category_raw)
        self.assertEqual("https://www.popga.co.kr/popup/8366", row.detail_url)
        self.assertEqual([], row.parse_warnings)

    def test_unknown_seoul_label_is_kept_for_validation(self) -> None:
        rows = parse_card_blocks([
            {
                "detail_url": "/popup/9999",
                "card_text": (
                    "오픈 예정\n테스트 팝업\n새로운지역라벨\n"
                    "26. 09. 01 - 26. 09. 17\n패션"
                ),
            }
        ])

        self.assertEqual(1, len(rows))
        self.assertIn(
            "unrecognized_seoul_area_label",
            rows[0].parse_warnings,
        )

    def test_open_ended_period_is_kept_without_inventing_end_date(self) -> None:
        rows = parse_card_blocks([
            {
                "detail_url": "/popup/8785",
                "image_url": "https://cdn.popga.co.kr/example.webp",
                "card_text": (
                    "찜하기\n오픈 예정\n피어 팝업\n용산\n"
                    "26. 09. 01 - 추후 공지\n패션"
                ),
            }
        ])

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("8785", row.source_id)
        self.assertEqual("2026-09-01", row.start_date)
        self.assertIsNone(row.end_date)
        self.assertEqual("패션", row.category_raw)
        self.assertEqual(
            "https://cdn.popga.co.kr/example.webp",
            row.image_url,
        )
        self.assertIn(
            "end_date_missing_source_open_ended",
            row.parse_warnings,
        )

    def test_duplicate_detail_links_are_deduplicated(self) -> None:
        block = {
            "detail_url": "/popup/1234",
            "card_text": (
                "운영중\n테스트 팝업\n성수\n"
                "26. 08. 20 - 26. 09. 02\n패션"
            ),
        }
        self.assertEqual(1, len(parse_card_blocks([block, block])))

    def test_body_text_fallback_uses_hash_id(self) -> None:
        rows = parse_list_lines([
            "운영중",
            "fallback 팝업",
            "성수",
            "26. 08. 20 - 26. 09. 02",
            "패션",
        ])

        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0].source_id.startswith("hash_"))
        self.assertIn(
            "detail_url_missing_fallback_id",
            rows[0].parse_warnings,
        )

    def test_invalid_calendar_date_is_not_parsed(self) -> None:
        rows = parse_card_blocks([
            {
                "detail_url": "/popup/7777",
                "card_text": (
                    "운영중\n잘못된 날짜\n성수\n"
                    "26. 02. 31 - 26. 03. 01\n패션"
                ),
            }
        ])
        self.assertEqual([], rows)


if __name__ == "__main__":
    unittest.main()
