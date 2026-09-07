from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from run_daily import (
    retention_warning,
    validate_dayforyou,
    validate_popga,
    validate_popply,
)
from run_integrate import get_master_commit_block_reasons


class V090Tests(unittest.TestCase):
    def test_retention_gate_blocks_large_source_drop(self):
        warning = retention_warning(
            "popga", 100, 271,
            min_retention=0.65,
            min_source_count=10,
        )
        self.assertIsNotNone(warning)
        self.assertIn("dropped", warning)

    def test_retention_gate_accepts_normal_change(self):
        warning = retention_warning(
            "popply", 150, 154,
            min_retention=0.65,
            min_source_count=10,
        )
        self.assertIsNone(warning)

    def test_dayforyou_blocks_unresolved_llm_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "final_popup_db.jsonl").write_text("{}\n", encoding="utf-8")
            report = {
                "seoul_total": 400,
                "detail_success": 60,
                "detail_failed": 0,
                "llm_candidate_count": 2,
                "llm_executed": True,
                "llm_report": {"manual_review": 1, "api_calls": 1},
            }
            errors, warnings, metrics = validate_dayforyou(
                run_dir, report,
                previous_count=406,
                min_retention=0.65,
                min_source_count=10,
                max_detail_failure_rate=0.05,
            )
            self.assertTrue(any("manual review" in x for x in errors))
            self.assertEqual(metrics["llm_calls"], 1)
            self.assertEqual(warnings, [])

    def test_popga_requires_full_detail_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report = {
                "candidate_count": 271,
                "detail_fetch": {"requested_count": 200, "failed_count": 0},
            }
            errors, _warnings, _metrics = validate_popga(
                run_dir, report,
                previous_count=270,
                min_retention=0.65,
                min_source_count=10,
                max_detail_failure_rate=0.05,
            )
            self.assertTrue(any("normalized_with_details" in x for x in errors))
            self.assertTrue(any("requested_count" in x for x in errors))

    def test_popply_partial_probe_cannot_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "normalized_with_details.jsonl").write_text("{}\n", encoding="utf-8")
            report = {
                "candidate_count": 154,
                "detail_fetch": {
                    "requested_count": 154,
                    "failed_count": 0,
                    "is_partial": True,
                },
            }
            errors, _warnings, _metrics = validate_popply(
                run_dir, report,
                previous_count=154,
                min_retention=0.65,
                min_source_count=10,
                max_detail_failure_rate=0.05,
            )
            self.assertTrue(any("partial" in x for x in errors))

    def test_master_commit_is_blocked_when_review_remains(self):
        reasons = get_master_commit_block_reasons(
            [{"classification": "REVIEW"}],
            [{"decision": "REVIEW_NAME"}],
            [{"popup_id": "preview_1"}],
        )
        self.assertIn("classification_review=1", reasons)
        self.assertIn("duplicate_review=1", reasons)

    def test_master_commit_is_allowed_for_clean_nonempty_canonical(self):
        reasons = get_master_commit_block_reasons([], [], [{"popup_id": "preview_1"}])
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
