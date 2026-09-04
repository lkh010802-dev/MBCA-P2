from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from crawlers.popply import _overlap_ratio
from run_daily import validate_popply
from storage.csv_export import export_popup_csv


class V095Tests(unittest.TestCase):
    def test_overlap_ratio_detects_duplicated_status_cards(self):
        active = {"1", "2", "3", "4"}
        stale_upcoming = {"1", "2", "3", "4"}
        real_upcoming = {"10", "11"}
        self.assertEqual(1.0, _overlap_ratio(active, stale_upcoming))
        self.assertEqual(0.0, _overlap_ratio(active, real_upcoming))

    def test_popply_suspicious_status_refresh_blocks_daily_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "normalized_with_details.jsonl").write_text("{}\n", encoding="utf-8")
            report = {
                "candidate_count": 97,
                "crawl_diagnostics": {
                    "status_refresh_suspect_count": 1,
                    "status_refresh_suspect_statuses": ["오픈 예정"],
                    "status_retry_counts": {"진행 중": 0, "오픈 예정": 1},
                    "status_overlap_ratios": {"진행 중": 0.0, "오픈 예정": 1.0},
                },
                "detail_fetch": {
                    "requested_count": 97,
                    "failed_count": 0,
                    "is_partial": False,
                    "core_detail_incomplete_count": 0,
                },
            }
            errors, _warnings, metrics = validate_popply(
                run_dir,
                report,
                previous_count=134,
                min_retention=0.65,
                min_source_count=10,
                max_detail_failure_rate=0.05,
            )
            self.assertTrue(any("status filter card refresh" in item for item in errors))
            self.assertEqual(1, metrics["status_refresh_suspect"])

    def test_backend_csv_exports_current_active_and_upcoming_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20260901_popup.csv"
            rows = [
                {
                    "popup_id": "popup_a",
                    "name": "활성 팝업",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-10",
                    "master_status": "ACTIVE",
                    "seen_in_latest_run": True,
                    "sources": ["popga", "popply"],
                    "tags": ["성수", "팝업"],
                },
                {
                    "popup_id": "popup_b",
                    "name": "예정 팝업",
                    "start_date": "2026-09-05",
                    "end_date": "2026-09-20",
                    "master_status": "UPCOMING",
                    "seen_in_latest_run": True,
                    "sources": ["dayforyou"],
                },
                {
                    "popup_id": "popup_c",
                    "name": "종료 팝업",
                    "master_status": "ENDED",
                    "seen_in_latest_run": False,
                    "sources": ["popga"],
                },
                {
                    "popup_id": "popup_d",
                    "name": "미확인",
                    "master_status": "UNVERIFIED",
                    "seen_in_latest_run": False,
                    "sources": ["popply"],
                },
            ]
            count = export_popup_csv(rows, path)
            self.assertEqual(2, count)
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                result = list(csv.DictReader(handle))
            self.assertEqual(["popup_a", "popup_b"], [row["popup_id"] for row in result])
            self.assertEqual("popga|popply", result[0]["sources"])
            self.assertEqual("2", result[0]["source_count"])
            self.assertIn("성수", result[0]["tags"])


if __name__ == "__main__":
    unittest.main()
