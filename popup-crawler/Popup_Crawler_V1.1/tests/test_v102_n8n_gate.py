from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from run_daily import validate_popply


class V102Tests(unittest.TestCase):
    def _run(self, *, failed: int, requested: int = 129):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "normalized_with_details.jsonl").write_text("{}\n", encoding="utf-8")
            (run_dir / "normalized_for_integration.jsonl").write_text("{}\n", encoding="utf-8")
            report = {
                "candidate_count": requested,
                "detail_fetch": {
                    "requested_count": requested,
                    "failed_count": failed,
                    "is_partial": False,
                    "core_detail_incomplete_count": failed,
                    "integration_usable_count": requested - failed,
                    "quarantine_count": failed,
                    "quarantine_names": [f"q{i}" for i in range(failed)],
                },
            }
            return validate_popply(
                run_dir,
                report,
                previous_count=requested,
                min_retention=0.65,
                min_source_count=10,
                max_detail_failure_rate=0.06,
                max_core_incomplete_count=10,
                max_core_incomplete_rate=0.06,
            )

    def test_seven_of_129_is_quarantined_and_allowed(self):
        errors, warnings, metrics = self._run(failed=7)
        self.assertEqual([], errors)
        self.assertTrue(any("quarantined 7/129" in x for x in warnings))
        self.assertEqual(122, metrics["integration_usable_count"])

    def test_eight_of_129_still_blocks(self):
        errors, _warnings, _metrics = self._run(failed=8)
        self.assertTrue(any("detail failure rate" in x for x in errors))


if __name__ == "__main__":
    unittest.main()
