import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from conditions import (
    calculate_time_window,
    resolve_datetimes,
    resolve_end_location,
    resolve_end_time,
    resolve_start_location,
    resolve_start_time,
)
from models import RecommendRequest, StructuredConditions


SEOUL = ZoneInfo("Asia/Seoul")


class StartTimePeriodTests(unittest.TestCase):
    def test_evening_before_period_starts_at_1800(self):
        now = datetime(2026, 9, 14, 11, 0, tzinfo=SEOUL)
        resolved = resolve_start_time(
            StructuredConditions(start_time_period="evening"),
            current_datetime=now,
        )
        datetimes = resolve_datetimes(
            resolved,
            resolve_end_time(StructuredConditions()),
            current_datetime=now,
        )

        self.assertEqual(
            datetimes["start_datetime"],
            datetime(2026, 9, 14, 18, 0, tzinfo=SEOUL),
        )

    def test_evening_during_period_uses_current_time(self):
        now = datetime(2026, 9, 14, 19, 30, tzinfo=SEOUL)

        resolved = resolve_start_time(
            StructuredConditions(start_time_period="evening"),
            current_datetime=now,
        )

        self.assertEqual(resolved["start_time"], "19:30")

    def test_exact_start_time_keeps_priority_over_period(self):
        now = datetime(2026, 9, 14, 11, 0, tzinfo=SEOUL)
        resolved = resolve_start_time(
            StructuredConditions(start_time="17:00"),
            current_datetime=now,
        )

        self.assertEqual(resolved, {"source": "text", "start_time": "17:00"})

    def test_period_without_end_time_does_not_create_time_window(self):
        now = datetime(2026, 9, 14, 11, 0, tzinfo=SEOUL)
        datetimes = resolve_datetimes(
            resolve_start_time(
                StructuredConditions(start_time_period="evening"),
                current_datetime=now,
            ),
            resolve_end_time(StructuredConditions()),
            current_datetime=now,
        )

        self.assertIsNone(calculate_time_window(datetimes)["time_window_minutes"])

    def test_missing_period_preserves_current_time_behavior(self):
        now = datetime(2026, 9, 14, 11, 23, tzinfo=SEOUL)

        resolved = resolve_start_time(
            StructuredConditions(),
            current_datetime=now,
        )

        self.assertEqual(resolved, {"source": "current", "start_time": "11:23"})

    def test_passed_period_does_not_roll_to_next_day(self):
        now = datetime(2026, 9, 14, 16, 0, tzinfo=SEOUL)

        resolved = resolve_start_time(
            StructuredConditions(start_time_period="morning"),
            current_datetime=now,
        )

        self.assertEqual(resolved, {"source": "current", "start_time": "16:00"})


class ExplicitLocationPriorityTests(unittest.TestCase):
    def test_explicit_start_location_has_priority_over_gps(self):
        request = RecommendRequest(
            user_message="지금 대림인데 8시까지 신림 가기 전에 어디 들를 데가 있을까?",
            gps_latitude=37.5665,
            gps_longitude=126.9780,
        )
        conditions = StructuredConditions(
            start_location_text="대림",
            end_location_text="신림",
            end_time="20:00",
        )

        self.assertEqual(
            resolve_start_location(request, conditions),
            {
                "source": "text",
                "location_text": "대림",
                "latitude": None,
                "longitude": None,
            },
        )
        self.assertEqual(
            resolve_end_location(conditions)["location_text"],
            "신림",
        )
        self.assertEqual(resolve_end_time(conditions)["end_time"], "20:00")

    def test_gps_is_used_only_without_explicit_start_location(self):
        request = RecommendRequest(
            user_message="8시까지 신림 가기 전에 어디 들를까?",
            gps_latitude=37.5665,
            gps_longitude=126.9780,
        )

        self.assertEqual(
            resolve_start_location(request, StructuredConditions()),
            {
                "source": "gps",
                "location_text": None,
                "latitude": 37.5665,
                "longitude": 126.9780,
            },
        )


if __name__ == "__main__":
    unittest.main()
