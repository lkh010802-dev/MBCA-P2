from __future__ import annotations

import unittest
from datetime import date

from integration.classifier import classify_dayforyou_final
from integration.common import clean_description
from integration.duplicate import generate_duplicate_candidates
from backend_adapter.popup_backend_adapter import normalize_popup_row
from normalization.operation_hours import parse_operation_schedule, resolve_schedule_for_date


class OperationHoursRegressionTests(unittest.TestCase):
    def test_prose_su_is_not_wednesday(self):
        raw = (
            "13:00 - 16:00 *모든 기프트는 한정 수량으로, 소진 시 별도의 안내 없이 "
            "이벤트가 종료됩니다. *날씨 상황에 따라 상품이 변경될 수 있습니다."
        )
        schedule, opening, closing = parse_operation_schedule([raw])
        self.assertEqual(7, len(schedule[0]["days"]))
        self.assertEqual(("13:00", "16:00"), (opening, closing))
        monday = resolve_schedule_for_date(schedule, date(2026, 9, 7))
        self.assertEqual("13:00", monday["today_opening_time"])
        self.assertFalse(monday["today_closed"])

    def test_popga_mail_typo_is_repaired_to_daily(self):
        schedule, opening, closing = parse_operation_schedule(["메일 10:30 ~ 22:00"])
        self.assertEqual(7, len(schedule[0]["days"]))
        self.assertEqual(("10:30", "22:00"), (opening, closing))

    def test_unlisted_weekday_is_closed_when_explicit_days_are_published(self):
        schedule, _, _ = parse_operation_schedule(["수-토 13:00 ~ 19:00"])
        monday = resolve_schedule_for_date(schedule, date(2026, 9, 7))
        self.assertTrue(monday["today_closed"])
        self.assertIsNone(monday["today_opening_time"])


class DescriptionRegressionTests(unittest.TestCase):
    def test_truncated_api_payload_is_removed(self):
        self.assertIsNone(clean_description('" {"seq":"141604","totCnt":0,"totalPageCnt":0,"totTy "'))

    def test_normal_description_survives(self):
        text = "성수에서 열리는 향수 팝업입니다."
        self.assertEqual(text, clean_description(text))


class DayForYouClassificationRegressionTests(unittest.TestCase):
    def _row(self, name: str) -> dict:
        return {
            "record_id": "dayforyou:test",
            "source": "dayforyou",
            "source_id": "test",
            "name": name,
            "name_raw": name,
            "source_record_raw": {},
        }

    def test_kpop_contest_recruitment_is_not_popup(self):
        result = classify_dayforyou_final(self._row("2026 K-POP CONTEST 지원자 모집"))
        self.assertEqual("NON_POPUP", result["classification"])

    def test_museum_earlybird_is_not_popup(self):
        result = classify_dayforyou_final(
            self._row("[롯데뮤지엄] 《이강소 : 일어나고 사라지는》 얼리버드 시작")
        )
        self.assertEqual("NON_POPUP", result["classification"])

    def test_explicit_popup_at_museum_still_wins(self):
        result = classify_dayforyou_final(self._row("롯데뮤지엄 굿즈 팝업"))
        self.assertEqual("POPUP", result["classification"])


class SameSourceDuplicateRegressionTests(unittest.TestCase):
    def _row(self, source_id: str, name: str) -> dict:
        return {
            "record_id": f"dayforyou:{source_id}",
            "source": "dayforyou",
            "source_id": source_id,
            "name": name,
            "name_raw": name,
            "address": "서울 송파구 충민로 66 현대아울렛 가든파이브점",
            "address_base": "서울 송파구 충민로 66",
            "district": "송파구",
            "start_date": "2026-09-04",
            "end_date": "2026-09-10",
            "classification": "POPUP",
            "official_url": None,
            "tags": [],
            "categories": [],
        }

    def test_editorial_prefix_duplicate_is_auto_merged(self):
        left = self._row("37049", "[COMING SOON] 노스페이스 에디션 1 쇼핑과 기부를 한번에!")
        right = self._row("37148", "노스페이스 에디션 1 쇼핑과 기부를 한번에!")
        candidates = generate_duplicate_candidates([left, right])
        self.assertEqual(1, len(candidates))
        self.assertEqual("AUTO_DUPLICATE", candidates[0]["decision"])

    def test_same_place_same_dates_but_different_names_do_not_merge(self):
        left = self._row("1", "브랜드 A 팝업")
        right = self._row("2", "브랜드 B 팝업")
        candidates = generate_duplicate_candidates([left, right])
        self.assertEqual([], candidates)


class BackendAdapterDescriptionRegressionTests(unittest.TestCase):
    def test_backend_json_also_drops_api_payload_fragment(self):
        row = {
            "popup_id": "popup_test",
            "name": "테스트 팝업",
            "latitude": "37.5",
            "longitude": "127.0",
            "description": '" {"seq":"141604","totCnt":0,"totalPageCnt":0,"totTy"',
        }
        place = normalize_popup_row(row)
        self.assertIsNotNone(place)
        self.assertIsNone(place["description"])


if __name__ == "__main__":
    unittest.main()
