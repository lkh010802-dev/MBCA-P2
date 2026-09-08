from __future__ import annotations

import unittest
from datetime import date

from integration.master import update_master


class ReviewToleranceHotfixTests(unittest.TestCase):
    def test_review_protected_master_is_not_marked_ended_or_missing(self):
        old = {
            "popup_id": "popup_old",
            "name": "Example",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "source_refs": [{"source": "popply", "source_id": "5917"}],
            "seen_in_latest_run": True,
            "missing_run_count": 0,
            "master_status": "ACTIVE",
            "master_updated_at": "2026-09-06T08:00:00+09:00",
        }
        result, report = update_master(
            [],
            [old],
            today=date(2026, 9, 7),
            run_timestamp="2026-09-07T10:00:00+09:00",
            protected_source_refs={("popply", "5917")},
        )
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["seen_in_latest_run"])
        self.assertEqual(result[0]["missing_run_count"], 0)
        self.assertEqual(result[0]["master_status"], "ACTIVE")
        self.assertTrue(result[0]["skipped_due_to_review"])
        self.assertEqual(report["review_protected_master_count"], 1)
        self.assertEqual(report["absent_from_latest_run_count"], 0)


if __name__ == "__main__":
    unittest.main()
