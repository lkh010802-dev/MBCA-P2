import unittest
from datetime import date
from unittest.mock import patch

from seoul_culture_service import (
    get_nearby_current_exhibitions,
    normalize_seoul_culture_event,
    parse_operation_hours,
)


ALL_DAYS = [
    "MON",
    "TUE",
    "WED",
    "THU",
    "FRI",
    "SAT",
    "SUN",
]


class SeoulCultureOperationHoursTests(unittest.TestCase):
    def test_parses_weekday_weekend_and_closed_day(self):
        result = parse_operation_hours(
            "월~금 10:00~18:00, 토 10:00~14:00, 일 휴관"
        )

        self.assertEqual(result["status"], "parsed")
        self.assertEqual(
            result["schedule"],
            [
                {
                    "days": ["MON", "TUE", "WED", "THU", "FRI"],
                    "opening_time": "10:00",
                    "closing_time": "18:00",
                    "closed": False,
                },
                {
                    "days": ["SAT"],
                    "opening_time": "10:00",
                    "closing_time": "14:00",
                    "closed": False,
                },
                {
                    "days": ["SUN"],
                    "opening_time": None,
                    "closing_time": None,
                    "closed": True,
                },
            ],
        )

    def test_splits_operation_hours_around_break_time(self):
        result = parse_operation_hours(
            "매일 10:00~20:00, 브레이크 타임 14:00~15:00"
        )

        self.assertEqual(result["status"], "parsed")
        self.assertEqual(
            result["schedule"],
            [
                {
                    "days": ALL_DAYS,
                    "opening_time": "10:00",
                    "closing_time": "14:00",
                    "closed": False,
                },
                {
                    "days": ALL_DAYS,
                    "opening_time": "15:00",
                    "closing_time": "20:00",
                    "closed": False,
                },
            ],
        )

    def test_does_not_guess_ambiguous_ampm(self):
        result = parse_operation_hours("오전 9시~6시")

        self.assertEqual(result["status"], "unparsed")
        self.assertEqual(result["schedule"], [])
        self.assertEqual(result["raw_text"], "오전 9시~6시")

    def test_keeps_seasonal_hours_unparsed(self):
        raw = "동절기 10:00~17:00 / 하절기 10:00~18:00"

        result = parse_operation_hours(raw)

        self.assertEqual(result["status"], "unparsed")
        self.assertEqual(result["schedule"], [])
        self.assertEqual(result["raw_text"], raw)

    def test_returns_missing_without_operation_hours(self):
        self.assertEqual(
            parse_operation_hours(None),
            {
                "raw_text": None,
                "raw_blocks": [],
                "schedule": [],
                "status": "missing",
            },
        )

    def test_normalization_preserves_event_dates_and_opening_hours(self):
        event = {
            "CODENAME": "전시/미술",
            "TITLE": "테스트 전시",
            "STRTDATE": "2026-09-01",
            "END_DATE": "2026-09-30",
            "PLACE": "테스트 미술관",
            "LAT": "37.55",
            "LOT": "126.98",
            "PRO_TIME": "매일 10:00~18:00",
        }

        place = normalize_seoul_culture_event(
            event,
            reference_date=date(2026, 9, 7),
        )

        self.assertEqual(place["start_at"], "2026-09-01")
        self.assertEqual(place["end_at"], "2026-09-30")
        self.assertEqual(place["opening_hours"], "매일 10:00~18:00")
        self.assertEqual(place["operation_hours_raw"], ["매일 10:00~18:00"])
        self.assertEqual(place["operation_schedule_status"], "parsed")
        self.assertEqual(
            place["operation_schedule"],
            [
                {
                    "days": ALL_DAYS,
                    "opening_time": "10:00",
                    "closing_time": "18:00",
                    "closed": False,
                }
            ],
        )

    def test_keeps_overnight_hours_unparsed_but_accepts_24_hour_notation(self):
        overnight = parse_operation_hours("매일 11:00~02:00")
        full_day = parse_operation_hours("매일 00:00~24:00")

        self.assertEqual(overnight["status"], "unparsed")
        self.assertEqual(overnight["schedule"], [])
        self.assertEqual(full_day["status"], "parsed")
        self.assertEqual(full_day["schedule"][0]["closing_time"], "24:00")

    @patch("seoul_culture_service.get_nearby_current_seoul_culture_places")
    def test_existing_nearby_exhibitions_wrapper_is_preserved(self, mock_nearby):
        mock_nearby.return_value = [{"name": "테스트 전시"}]

        result = get_nearby_current_exhibitions(
            latitude=37.55,
            longitude=126.98,
            max_distance_m=1500,
        )

        self.assertEqual(result, [{"name": "테스트 전시"}])
        mock_nearby.assert_called_once_with(
            latitude=37.55,
            longitude=126.98,
            max_distance_m=1500,
            reference_date=None,
            api_key=None,
        )


if __name__ == "__main__":
    unittest.main()
