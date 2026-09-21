import json
import os
import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from popup_service import (
    PopupDataError,
    _get_popup_data_paths,
    load_current_popup_places,
    load_popup_places,
    normalize_popup_place,
)


def make_popup(**overrides):
    popup = {
        "source": "popup",
        "source_id": "popup_1",
        "name": "테스트 팝업",
        "latitude": 37.55,
        "longitude": 126.98,
        "category": "shopping",
        "category_detail": "패션",
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "status": "ACTIVE",
        "opening_time": "10:00",
        "closing_time": "20:00",
        "operation_schedule": [
            {
                "days": ["MON", "TUE", "WED", "THU", "FRI"],
                "opening_time": "10:00",
                "closing_time": "20:00",
                "closed": False,
                "special_days": ["PUBLIC_HOLIDAY"],
            }
        ],
        "confidence": 0.95,
    }
    popup.update(overrides)
    return popup


class PopupServiceTests(unittest.TestCase):
    def write_json(self, directory, data, name="popups.json"):
        path = Path(directory) / name
        path.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_loads_and_normalizes_popup_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, [make_popup()])

            places = load_popup_places(path)

        self.assertEqual(len(places), 1)
        place = places[0]
        self.assertEqual(place["start_at"], "2026-09-01")
        self.assertEqual(place["end_at"], "2026-09-30")
        self.assertNotIn("start_date", place)
        self.assertNotIn("end_date", place)
        self.assertEqual(place["category"], "shopping")
        self.assertEqual(place["confidence"], 0.95)

    def test_reuses_cached_file_data_and_returns_independent_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, [make_popup()])

            with patch("popup_service.json.load", wraps=json.load) as mock_load:
                first = load_popup_places(path)
                first[0]["name"] = "변경된 이름"
                second = load_popup_places(path)

        mock_load.assert_called_once()
        self.assertEqual(second[0]["name"], "테스트 팝업")

    def test_reloads_replaced_file_without_server_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, [make_popup(name="이전 팝업")])
            first = load_popup_places(path)
            previous_stat = path.stat()

            self.write_json(directory, [make_popup(name="새로운 팝업")])
            os.utime(
                path,
                ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1),
            )
            second = load_popup_places(path)

        self.assertEqual(first[0]["name"], "이전 팝업")
        self.assertEqual(second[0]["name"], "새로운 팝업")

    # 08:40 이전에는 전날 날짜의 팝업 파일만 운영 파일 후보로 사용한다.
    def test_popup_data_paths_use_yesterday_before_0840(self):
        now = datetime(
            2026,
            9,
            21,
            8,
            39,
            59,
            tzinfo=timezone(timedelta(hours=9)),
        )

        paths = _get_popup_data_paths(now)

        self.assertEqual(
            [path.name for path in paths],
            ["20260920_popup_places.json"],
        )

    # 08:40부터는 오늘 파일을 우선하고 실패 시 전날 파일을 사용한다.
    def test_popup_data_paths_use_today_then_yesterday_from_0840(self):
        now = datetime(
            2026,
            9,
            21,
            8,
            40,
            0,
            tzinfo=timezone(timedelta(hours=9)),
        )

        paths = _get_popup_data_paths(now)

        self.assertEqual(
            [path.name for path in paths],
            [
                "20260921_popup_places.json",
                "20260920_popup_places.json",
            ],
        )

    # 08:40 이전에는 전날 운영 파일을 정상적으로 읽는다.
    def test_current_loader_uses_yesterday_before_switch_time(self):
        with tempfile.TemporaryDirectory() as directory:
            yesterday = self.write_json(
                directory,
                [make_popup(name="전날 팝업")],
                "20260920_popup_places.json",
            )
            fallback = self.write_json(
                directory,
                [make_popup(name="비상 팝업")],
                "fallback.json",
            )

            with patch(
                "popup_service._get_popup_data_paths",
                return_value=(yesterday,),
            ), patch(
                "popup_service.FALLBACK_POPUP_DATA_PATH",
                fallback,
            ):
                places = load_current_popup_places()

        self.assertEqual(places[0]["name"], "전날 팝업")

    # 08:40 이후에는 오늘 운영 파일을 우선해서 읽는다.
    def test_current_loader_uses_today_after_switch_time(self):
        with tempfile.TemporaryDirectory() as directory:
            today = self.write_json(
                directory,
                [make_popup(name="오늘 팝업")],
                "20260921_popup_places.json",
            )
            yesterday = self.write_json(
                directory,
                [make_popup(name="전날 팝업")],
                "20260920_popup_places.json",
            )
            fallback = self.write_json(
                directory,
                [make_popup(name="비상 팝업")],
                "fallback.json",
            )

            with patch(
                "popup_service._get_popup_data_paths",
                return_value=(today, yesterday),
            ), patch(
                "popup_service.FALLBACK_POPUP_DATA_PATH",
                fallback,
            ):
                places = load_current_popup_places()

        self.assertEqual(places[0]["name"], "오늘 팝업")

    # 08:40 이후 오늘 파일이 없으면 전날 파일로 fallback한다.
    def test_current_loader_falls_back_to_yesterday_when_today_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            today = Path(directory) / "20260921_popup_places.json"
            yesterday = self.write_json(
                directory,
                [make_popup(name="전날 팝업")],
                "20260920_popup_places.json",
            )
            fallback = self.write_json(
                directory,
                [make_popup(name="비상 팝업")],
                "fallback.json",
            )

            with patch(
                "popup_service._get_popup_data_paths",
                return_value=(today, yesterday),
            ), patch(
                "popup_service.FALLBACK_POPUP_DATA_PATH",
                fallback,
            ):
                places = load_current_popup_places()

        self.assertEqual(places[0]["name"], "전날 팝업")

    # 오늘과 전날 운영 파일을 모두 사용할 수 없으면 기본 스냅샷으로 fallback한다.
    def test_current_loader_falls_back_to_snapshot_when_daily_files_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            today = Path(directory) / "20260921_popup_places.json"
            yesterday = Path(directory) / "20260920_popup_places.json"
            fallback = self.write_json(
                directory,
                [make_popup(name="비상 팝업")],
                "fallback.json",
            )

            with patch(
                "popup_service._get_popup_data_paths",
                return_value=(today, yesterday),
            ), patch(
                "popup_service.FALLBACK_POPUP_DATA_PATH",
                fallback,
            ):
                places = load_current_popup_places()

        self.assertEqual(places[0]["name"], "비상 팝업")

    # 날짜별 운영 파일과 기본 스냅샷을 모두 사용할 수 없으면 빈 목록을 반환한다.
    def test_current_loader_returns_empty_when_all_files_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            today = Path(directory) / "20260921_popup_places.json"
            yesterday = Path(directory) / "20260920_popup_places.json"
            fallback = Path(directory) / "missing-fallback.json"

            with patch(
                "popup_service._get_popup_data_paths",
                return_value=(today, yesterday),
            ), patch(
                "popup_service.FALLBACK_POPUP_DATA_PATH",
                fallback,
            ):
                places = load_current_popup_places()

        self.assertEqual(places, [])

    def test_preserves_missing_end_date(self):
        place = normalize_popup_place(make_popup(end_date=None))

        self.assertIsNone(place["end_at"])

    def test_preserves_special_days_and_normal_hours(self):
        place = normalize_popup_place(make_popup())
        schedule = place["operation_schedule"][0]

        self.assertEqual(schedule["special_days"], ["PUBLIC_HOLIDAY"])
        self.assertFalse(schedule["closes_next_day"])

    def test_marks_overnight_closing_time(self):
        popup = make_popup(
            opening_time="11:00",
            closing_time="02:00",
            operation_schedule=[
                {
                    "days": ["FRI", "SAT"],
                    "opening_time": "11:00",
                    "closing_time": "02:00",
                    "closed": False,
                }
            ],
        )

        place = normalize_popup_place(popup)

        self.assertTrue(
            place["operation_schedule"][0]["closes_next_day"]
        )

    def test_does_not_mark_24_hour_notation_as_next_day(self):
        popup = make_popup(
            opening_time="00:00",
            closing_time="24:00",
            operation_schedule=[
                {
                    "days": [
                        "MON",
                        "TUE",
                        "WED",
                        "THU",
                        "FRI",
                        "SAT",
                        "SUN",
                    ],
                    "opening_time": "00:00",
                    "closing_time": "24:00",
                    "closed": False,
                }
            ],
        )

        place = normalize_popup_place(popup)

        schedule = place["operation_schedule"][0]
        self.assertEqual(schedule["closing_time"], "24:00")
        self.assertFalse(schedule["closes_next_day"])

    def test_missing_operation_schedule_becomes_empty_list(self):
        place = normalize_popup_place(
            make_popup(operation_schedule=None)
        )

        self.assertEqual(place["operation_schedule"], [])

    def test_skips_invalid_records_without_breaking_valid_records(self):
        invalid_records = [
            "not-a-dict",
            make_popup(source_id=""),
            make_popup(source_id="bad-coordinate", latitude="invalid"),
            make_popup(source_id="out-of-range", longitude=200),
        ]
        valid_popup = make_popup(source_id="valid")

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(
                directory,
                [*invalid_records, valid_popup],
            )

            places = load_popup_places(path)

        self.assertEqual(
            [place["source_id"] for place in places],
            ["valid"],
        )

    def test_missing_file_raises_popup_data_error(self):
        with tempfile.TemporaryDirectory() as directory:
            missing_path = Path(directory) / "missing.json"

            with self.assertRaises(PopupDataError):
                load_popup_places(missing_path)

    def test_malformed_json_raises_popup_data_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed.json"
            path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(PopupDataError):
                load_popup_places(path)

    def test_non_list_root_raises_popup_data_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, {"places": []})

            with self.assertRaises(PopupDataError):
                load_popup_places(path)


if __name__ == "__main__":
    unittest.main()