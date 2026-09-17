import math
import unittest

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from place_availability import evaluate_place_availability
from popup_service import normalize_popup_place


SEOUL = ZoneInfo("Asia/Seoul")
ALL_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def at(day, hour, minute=0, tz=SEOUL):
    return datetime(2026, 9, day, hour, minute, tzinfo=tz)


def interval(opening="10:00", closing="20:00", **overrides):
    value = {
        "days": ALL_DAYS,
        "opening_time": opening,
        "closing_time": closing,
        "closed": False,
        "closes_next_day": False,
    }
    value.update(overrides)
    return value


def place(**overrides):
    value = {
        "start_at": "2026-09-01",
        "end_at": "2026-09-30",
        "operation_schedule_status": "parsed",
        "operation_schedule": [interval()],
    }
    value.update(overrides)
    return value


class PlaceAvailabilityTests(unittest.TestCase):
    def evaluate(self, current=at(7, 12), travel=0, **overrides):
        return evaluate_place_availability(place(**overrides), current, travel)

    def test_open_during_normal_hours(self):
        self.assertEqual(self.evaluate()["status"], "open")

    def test_open_at_exact_opening_time(self):
        self.assertEqual(self.evaluate(at(7, 10))["status"], "open")

    def test_closed_at_exact_closing_time(self):
        self.assertEqual(self.evaluate(at(7, 20))["status"], "closed")

    def test_not_yet_open_before_opening(self):
        result = self.evaluate(at(7, 9))
        self.assertEqual(result["status"], "not_yet_open")
        self.assertEqual(result["opening_at"], at(7, 10))

    def test_closed_after_last_interval(self):
        self.assertEqual(self.evaluate(at(7, 21))["status"], "closed")

    def test_break_time_is_not_yet_open(self):
        result = self.evaluate(
            at(7, 14, 30),
            operation_schedule=[interval("10:00", "14:00"), interval("15:00", "20:00")],
        )
        self.assertEqual(result["status"], "not_yet_open")
        self.assertEqual(result["opening_at"], at(7, 15))

    def test_open_in_second_interval(self):
        result = self.evaluate(
            at(7, 15, 30),
            operation_schedule=[interval("10:00", "14:00"), interval("15:00", "20:00")],
        )
        self.assertEqual(result["status"], "open")

    def test_explicit_closed_day_is_closed(self):
        result = self.evaluate(
            operation_schedule=[{
                "days": ["MON"],
                "opening_time": None,
                "closing_time": None,
                "closed": True,
            }],
        )
        self.assertEqual(result["status"], "closed")

    def test_overnight_is_open_on_opening_night(self):
        result = self.evaluate(
            at(11, 23),
            operation_schedule=[interval(
                "11:00", "02:00", days=["FRI"], closes_next_day=True,
            )],
        )
        self.assertEqual(result["status"], "open")

    def test_overnight_is_open_after_midnight(self):
        result = self.evaluate(
            at(12, 1),
            operation_schedule=[interval(
                "11:00", "02:00", days=["FRI"], closes_next_day=True,
            )],
        )
        self.assertEqual(result["status"], "open")
        self.assertEqual(result["closing_at"], at(12, 2))

    def test_overnight_is_closed_at_closing_time(self):
        result = self.evaluate(
            at(12, 2),
            operation_schedule=[interval(
                "11:00", "02:00", days=["FRI"], closes_next_day=True,
            )],
        )
        self.assertEqual(result["status"], "closed")

    def test_24_hour_interval(self):
        result = self.evaluate(
            at(7, 23, 59),
            operation_schedule=[interval("00:00", "24:00")],
        )
        self.assertEqual(result["status"], "open")
        self.assertEqual(result["closing_at"], at(8, 0))

    def test_24_hour_interval_is_closed_at_next_midnight(self):
        result = self.evaluate(
            at(8, 0),
            operation_schedule=[interval(
                "00:00", "24:00", days=["MON"],
            )],
        )
        self.assertEqual(result["status"], "closed")

    def test_parsed_schedule_is_evaluated(self):
        self.assertEqual(self.evaluate()["status"], "open")

    def test_partial_schedule_is_unknown(self):
        self.assertEqual(self.evaluate(operation_schedule_status="partial")["status"], "unknown")

    def test_unparsed_schedule_is_unknown(self):
        self.assertEqual(self.evaluate(operation_schedule_status="unparsed")["status"], "unknown")

    def test_missing_schedule_status_is_unknown(self):
        self.assertEqual(self.evaluate(operation_schedule_status="missing")["status"], "unknown")

    def test_absent_schedule_is_unknown(self):
        self.assertEqual(self.evaluate(operation_schedule=None)["status"], "unknown")

    def test_event_not_started(self):
        self.assertEqual(self.evaluate(at(7, 12), start_at="2026-09-08")["status"], "event_not_started")

    def test_event_ended(self):
        self.assertEqual(self.evaluate(at(7, 12), end_at="2026-09-06")["status"], "event_ended")

    def test_event_period_boundaries_are_inclusive(self):
        self.assertEqual(self.evaluate(start_at="2026-09-07", end_at="2026-09-07")["status"], "open")

    def test_end_date_overnight_extension(self):
        result = self.evaluate(
            at(12, 1),
            end_at="2026-09-11",
            operation_schedule=[interval(
                "18:00", "02:00", days=["FRI"], closes_next_day=True,
            )],
        )
        self.assertEqual(result["status"], "open")

    def test_special_day_only_schedule_is_unknown(self):
        result = self.evaluate(
            operation_schedule=[interval(special_days=["PUBLIC_HOLIDAY"])],
        )
        self.assertEqual(result["status"], "unknown")

    def test_timezone_aware_datetime_is_converted_to_seoul(self):
        result = self.evaluate(
            datetime(2026, 9, 7, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(result["arrival_at"], at(7, 12))

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(datetime(2026, 9, 7, 12))

    def test_negative_travel_minutes_is_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(travel=-1)

    def test_none_travel_minutes_is_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(travel=None)

    def test_bool_travel_minutes_is_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(travel=True)

    def test_nan_and_infinity_are_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.evaluate(travel=value)

    def test_travel_can_move_arrival_to_next_day(self):
        result = self.evaluate(
            at(7, 23, 30),
            travel=60,
            operation_schedule=[interval("00:00", "24:00")],
        )
        self.assertEqual(result["arrival_at"], at(8, 0, 30))
        self.assertEqual(result["status"], "open")

    def test_arrival_and_remaining_minutes_are_calculated(self):
        result = self.evaluate(at(7, 17), travel=30)
        self.assertEqual(result["arrival_at"], at(7, 17, 30))
        self.assertEqual(result["closing_at"], at(7, 20))
        self.assertEqual(result["remaining_minutes"], 150)

    def test_invalid_time_is_unknown(self):
        result = self.evaluate(
            operation_schedule=[interval("오전 10시", "20:00")],
        )
        self.assertEqual(result["status"], "unknown")

    def test_conflicting_open_and_closed_is_unknown(self):
        result = self.evaluate(
            operation_schedule=[
                interval(days=["MON"]),
                {
                    "days": ["MON"],
                    "opening_time": None,
                    "closing_time": None,
                    "closed": True,
                },
            ],
        )
        self.assertEqual(result["status"], "unknown")

    def test_popup_normalization_sets_schedule_status(self):
        popup = {
            "source_id": "popup-1",
            "name": "팝업",
            "category": "shopping",
            "latitude": 37.5,
            "longitude": 126.9,
            "operation_schedule": [interval()],
        }

        self.assertEqual(
            normalize_popup_place(popup)["operation_schedule_status"],
            "parsed",
        )

    def test_popup_schedule_status_rejects_or_marks_invalid_data(self):
        base = {
            "source_id": "popup-1",
            "name": "팝업",
            "category": "shopping",
            "latitude": 37.5,
            "longitude": 126.9,
        }

        missing = normalize_popup_place({**base, "operation_schedule": []})
        unparsed = normalize_popup_place({
            **base,
            "operation_schedule": [interval("오전 10시", "20:00")],
        })
        partial = normalize_popup_place({
            **base,
            "operation_schedule": [interval(), interval("bad", "20:00")],
        })

        self.assertEqual(missing["operation_schedule_status"], "missing")
        self.assertEqual(unparsed["operation_schedule_status"], "unparsed")
        self.assertEqual(partial["operation_schedule_status"], "partial")


if __name__ == "__main__":
    unittest.main()
