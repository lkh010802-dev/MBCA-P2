from __future__ import annotations

import unittest

from integration.changes import build_daily_changes


class V093ChangeTrackingTests(unittest.TestCase):
    def row(
        self,
        popup_id: str,
        *,
        name: str = "테스트 팝업",
        status: str = "ACTIVE",
        seen: bool = True,
        start: str = "2026-08-01",
        end: str = "2026-09-30",
        address: str = "서울 성동구 테스트로 1",
        sources: list[str] | None = None,
    ) -> dict:
        return {
            "popup_id": popup_id,
            "name": name,
            "master_status": status,
            "seen_in_latest_run": seen,
            "start_date": start,
            "end_date": end,
            "address": address,
            "address_base": address,
            "venue_name": None,
            "district": "성동구",
            "category": "팝업스토어",
            "sources": sources or ["popga"],
        }

    def test_same_snapshot_has_zero_changes(self):
        old = [self.row("popup_1")]
        report, buckets = build_daily_changes(old, [dict(old[0])])
        self.assertFalse(report["has_changes"])
        self.assertEqual(0, report["new_popup_count"])
        self.assertTrue(all(not rows for rows in buckets.values()))

    def test_new_popup_is_reported(self):
        report, buckets = build_daily_changes([], [self.row("popup_new", name="새 팝업")])
        self.assertEqual(1, report["new_popup_count"])
        self.assertEqual("새 팝업", buckets["new_popups"][0]["name"])

    def test_field_change_records_before_after(self):
        old = [self.row("popup_1", end="2026-09-30")]
        new = [self.row("popup_1", end="2026-10-05")]
        report, buckets = build_daily_changes(old, new)
        self.assertEqual(1, report["changed_popup_count"])
        self.assertEqual(
            {"before": "2026-09-30", "after": "2026-10-05"},
            buckets["changed_popups"][0]["changes"]["end_date"],
        )
        self.assertEqual(1, report["changed_field_counts"]["end_date"])

    def test_source_coverage_change_is_reported(self):
        old = [self.row("popup_1", sources=["popga"])]
        new = [self.row("popup_1", sources=["popga", "popply"])]
        report, buckets = build_daily_changes(old, new)
        self.assertEqual(1, report["source_change_count"])
        self.assertEqual(["popply"], buckets["source_changes"][0]["sources_added"])

    def test_missing_active_becomes_newly_unverified_once(self):
        old = [self.row("popup_1", status="ACTIVE", seen=True)]
        new = [self.row("popup_1", status="UNVERIFIED", seen=False)]
        report, _ = build_daily_changes(old, new)
        self.assertEqual(1, report["newly_unverified_count"])
        # Repeating the same unverified state should not alert again.
        report2, _ = build_daily_changes(new, [dict(new[0])])
        self.assertEqual(0, report2["newly_unverified_count"])

    def test_newly_ended_is_reported_once(self):
        old = [self.row("popup_1", status="ACTIVE", seen=True)]
        new = [self.row("popup_1", status="ENDED", seen=False)]
        report, _ = build_daily_changes(old, new)
        self.assertEqual(1, report["newly_ended_count"])
        report2, _ = build_daily_changes(new, [dict(new[0])])
        self.assertEqual(0, report2["newly_ended_count"])

    def test_reappeared_after_unverified_is_reported(self):
        old = [self.row("popup_1", status="UNVERIFIED", seen=False)]
        new = [self.row("popup_1", status="ACTIVE", seen=True)]
        report, _ = build_daily_changes(old, new)
        self.assertEqual(1, report["reappeared_count"])

    def test_removed_master_row_is_reported_as_retired(self):
        old = [self.row("popup_1")]
        report, buckets = build_daily_changes(old, [])
        self.assertEqual(1, report["retired_from_master_count"])
        self.assertEqual("popup_1", buckets["retired_from_master"][0]["popup_id"])


if __name__ == "__main__":
    unittest.main()
