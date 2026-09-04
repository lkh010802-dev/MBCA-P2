from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from integration.common import common_from_dayforyou
from integration.duplicate import generate_duplicate_candidates
from integration.merge import merge_cluster
from storage.csv_export import CSV_FIELDS, export_popup_csv


class V101BackendReadyTests(unittest.TestCase):
    def test_dayforyou_common_keeps_operation_hours(self):
        row = {
            "source": "dayforyou", "source_id": "30071",
            "name": "[오베르캄프] 사워도우 에그타르트",
            "name_raw": "[오베르캄프] 사워도우 에그타르트",
            "address": "서울 송파구 올림픽로 300 롯데월드몰",
            "address_base": "서울 송파구 올림픽로 300",
            "district": "송파구", "start_date": "2026-02-13", "end_date": "2026-12-31",
            "detail_url": "https://dayforyou.com/getDetail?scheduleSeq=30071",
            "official_url": "https://www.lwt.co.kr/ko/event/view.do?seq=141604",
            "operation_hours_raw": ["10:30~22:00"],
            "operation_hours": ["10:30~22:00"],
            "crawled_at": "2026-09-04T09:00:00+09:00",
        }
        common = common_from_dayforyou(row, today=date(2026, 9, 4))
        self.assertEqual(["10:30~22:00"], common["operation_hours"])

    def test_canonical_derives_weekday_schedule(self):
        row = {
            "record_id": "dayforyou:30071", "source": "dayforyou", "source_id": "30071",
            "name": "오베르캄프 사워도우 에그타르트",
            "start_date": "2026-02-13", "end_date": "2026-12-31",
            "address": "서울 송파구 올림픽로 300 롯데월드몰",
            "address_base": "서울 송파구 올림픽로 300", "district": "송파구",
            "operation_hours": ["10:30~22:00"], "classification": "POPUP",
            "detail_url": "https://dayforyou.com/getDetail?scheduleSeq=30071",
            "official_url": "https://www.lwt.co.kr/ko/event/view.do?seq=141604",
            "source_url": "https://dayforyou.com/getScheduleList",
        }
        merged = merge_cluster([row], today=date(2026, 9, 4), duplicate_confidence=None)
        self.assertNotIn("opening_time", merged)
        self.assertNotIn("closing_time", merged)
        self.assertEqual(7, len(merged["operation_schedule"][0]["days"]))
        self.assertEqual("10:30", merged["operation_schedule"][0]["opening_time"])
        self.assertEqual("22:00", merged["operation_schedule"][0]["closing_time"])

    def test_same_source_exact_upstream_event_auto_merges(self):
        base = {
            "source": "dayforyou", "classification": "POPUP",
            "start_date": "2026-02-13", "end_date": "2026-12-31",
            "address": "서울 송파구 올림픽로 300 롯데월드몰",
            "address_base": "서울 송파구 올림픽로 300", "district": "송파구",
            "official_url": "https://www.lwt.co.kr/ko/event/view.do?seq=141604",
        }
        left = {**base, "record_id": "dayforyou:30071", "source_id": "30071", "name": "[오베르캄프] 사워도우 에그타르트"}
        right = {
            **base,
            "record_id": "dayforyou:28671", "source_id": "28671",
            "name": "오베르캄프 사워도우 에그타르트",
            "address": "서울 송파구 올림픽로 300 롯데월드타워몰",
            # Both variants normalize to the same street-level base address.
            "address_base": "서울 송파구 올림픽로 300",
        }
        candidates = generate_duplicate_candidates([left, right])
        self.assertEqual(1, len(candidates))
        self.assertEqual("AUTO_DUPLICATE", candidates[0]["decision"])
        self.assertTrue(candidates[0]["same_source_exact_identity"])

    def test_csv_has_backend_operation_fields(self):
        for field in (
            "operation_hours_raw", "operation_schedule", "today_day",
            "today_schedule", "today_opening_time", "today_closing_time",
            "today_closed",
        ):
            self.assertIn(field, CSV_FIELDS)
        self.assertNotIn("opening_time", CSV_FIELDS)
        self.assertNotIn("closing_time", CSV_FIELDS)

    def test_csv_exports_exact_today_window(self):
        row = {
            "popup_id": "popup_test",
            "name": "테스트 팝업",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "status": "ACTIVE",
            "master_status": "ACTIVE",
            "seen_in_latest_run": True,
            "sources": ["dayforyou"],
            "operation_hours": ["월-목 12:00-19:00", "금-일 09:00-22:00"],
            "operation_hours_raw": ["월-목 12:00-19:00", "금-일 09:00-22:00"],
            "operation_schedule": [
                {
                    "days": ["MON", "TUE", "WED", "THU"],
                    "opening_time": "12:00",
                    "closing_time": "19:00",
                },
                {
                    "days": ["FRI", "SAT", "SUN"],
                    "opening_time": "09:00",
                    "closing_time": "22:00",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "popup.csv"
            export_popup_csv([row], path, target_date=date(2026, 9, 4))  # Friday
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                exported = next(csv.DictReader(handle))
        self.assertEqual("FRI", exported["today_day"])
        self.assertEqual("09:00", exported["today_opening_time"])
        self.assertEqual("22:00", exported["today_closing_time"])
        self.assertEqual("false", exported["today_closed"])
        selected = json.loads(exported["today_schedule"])
        self.assertEqual(1, len(selected))
        self.assertEqual(["FRI", "SAT", "SUN"], selected[0]["days"])

    def test_csv_split_session_keeps_today_scalars_empty(self):
        row = {
            "popup_id": "popup_split",
            "name": "분리 운영",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "master_status": "ACTIVE",
            "seen_in_latest_run": True,
            "sources": ["dayforyou"],
            "operation_schedule": [
                {"days": ["FRI"], "opening_time": "11:00", "closing_time": "14:00"},
                {"days": ["FRI"], "opening_time": "17:00", "closing_time": "22:00"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "popup.csv"
            export_popup_csv([row], path, target_date=date(2026, 9, 4))
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                exported = next(csv.DictReader(handle))
        self.assertEqual("", exported["today_opening_time"])
        self.assertEqual("", exported["today_closing_time"])
        self.assertEqual("false", exported["today_closed"])
        self.assertEqual(2, len(json.loads(exported["today_schedule"])))



if __name__ == "__main__":
    unittest.main()
