from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from run_daily import validate_popply


class V096Tests(unittest.TestCase):
    def test_one_incomplete_record_is_quarantined_not_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "normalized_with_details.jsonl").write_text("{}\n", encoding="utf-8")
            (run_dir / "normalized_for_integration.jsonl").write_text("{}\n", encoding="utf-8")
            (run_dir / "detail_quarantine.jsonl").write_text(
                json.dumps({"source_id": "x", "name": "격리 팝업"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            report = {
                "candidate_count": 149,
                "detail_fetch": {
                    "requested_count": 149,
                    "failed_count": 1,
                    "is_partial": False,
                    "core_detail_incomplete_count": 1,
                    "integration_usable_count": 148,
                    "quarantine_count": 1,
                    "quarantine_names": ["격리 팝업"],
                },
            }
            errors, warnings, metrics = validate_popply(
                run_dir,
                report,
                previous_count=149,
                min_retention=0.65,
                min_source_count=10,
                max_detail_failure_rate=0.05,
                max_core_incomplete_count=2,
                max_core_incomplete_rate=0.02,
            )
            self.assertEqual([], errors)
            self.assertTrue(any("quarantined 1/149" in item for item in warnings))
            self.assertEqual(148, metrics["integration_usable_count"])
            self.assertEqual(1, metrics["quarantine_count"])
            self.assertTrue(metrics["output"].endswith("normalized_for_integration.jsonl"))

    def test_too_many_incomplete_records_still_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "normalized_with_details.jsonl").write_text("{}\n", encoding="utf-8")
            (run_dir / "normalized_for_integration.jsonl").write_text("{}\n", encoding="utf-8")
            report = {
                "candidate_count": 149,
                "detail_fetch": {
                    "requested_count": 149,
                    "failed_count": 4,
                    "is_partial": False,
                    "core_detail_incomplete_count": 4,
                    "integration_usable_count": 145,
                    "quarantine_count": 4,
                },
            }
            errors, _warnings, _metrics = validate_popply(
                run_dir,
                report,
                previous_count=149,
                min_retention=0.65,
                min_source_count=10,
                max_detail_failure_rate=0.05,
                max_core_incomplete_count=2,
                max_core_incomplete_rate=0.02,
            )
            self.assertTrue(any("exceeds quarantine allowance" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
