from __future__ import annotations

import unittest

from run_popga import (
    needs_list_retry,
    unchanged_active_ids as popga_unchanged_active_ids,
)
from run_popply import unchanged_active_ids as popply_unchanged_active_ids
from run_daily import VERSION


class V092Tests(unittest.TestCase):
    def _row(self, source_id: str, *, status: str = "ACTIVE", start: str = "2026-08-01") -> dict:
        return {
            "source_id": source_id,
            "status": status,
            "name_raw": "테스트 팝업",
            "start_date": start,
            "end_date": "2026-09-30",
            "detail_url": f"https://example.test/{source_id}",
        }

    def test_version(self):
        self.assertEqual("1.2", VERSION)

    def test_popga_unchanged_active_is_cache_candidate(self):
        current = [self._row("1")]
        previous = [self._row("1")]
        self.assertEqual({"1"}, popga_unchanged_active_ids(current, previous))

    def test_popga_upcoming_is_never_cache_candidate(self):
        current = [self._row("1", status="UPCOMING")]
        previous = [self._row("1", status="UPCOMING")]
        self.assertEqual(set(), popga_unchanged_active_ids(current, previous))

    def test_popga_list_drop_below_gate_retries(self):
        self.assertTrue(needs_list_retry(24, 254, min_retention=0.65))
        self.assertFalse(needs_list_retry(250, 254, min_retention=0.65))
        self.assertFalse(needs_list_retry(24, 0, min_retention=0.65))

    def test_popply_changed_dates_force_live_fetch(self):
        current = [self._row("2", start="2026-08-02")]
        previous = [self._row("2", start="2026-08-01")]
        self.assertEqual(set(), popply_unchanged_active_ids(current, previous))

    def test_popply_unchanged_active_is_cache_candidate(self):
        current = [self._row("2")]
        previous = [self._row("2")]
        self.assertEqual({"2"}, popply_unchanged_active_ids(current, previous))


if __name__ == "__main__":
    unittest.main()
