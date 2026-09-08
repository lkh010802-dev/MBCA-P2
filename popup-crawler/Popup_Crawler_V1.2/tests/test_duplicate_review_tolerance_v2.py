import unittest
from run_integrate import (
    get_master_commit_block_reasons,
    DEFAULT_MAX_CLASSIFICATION_REVIEW_COMMIT,
    DEFAULT_MAX_DUPLICATE_REVIEW_COMMIT,
)


class DuplicateReviewToleranceV2Test(unittest.TestCase):
    def test_defaults_are_production_quarantine_limits(self):
        self.assertEqual(DEFAULT_MAX_CLASSIFICATION_REVIEW_COMMIT, 10)
        self.assertEqual(DEFAULT_MAX_DUPLICATE_REVIEW_COMMIT, 25)

    def test_small_review_queue_does_not_block_safe_canonical(self):
        reasons = get_master_commit_block_reasons(
            classification_review=[{}],
            duplicate_review=[
                {"left_record_id": f"a:{i}", "right_record_id": f"b:{i}"}
                for i in range(5)
            ],
            canonical=[{"popup_id": "x"}],
            popup_record_count=200,
        )
        self.assertEqual(reasons, [])

    def test_large_duplicate_quarantine_spike_blocks(self):
        reviews = [
            {"left_record_id": f"a:{i}", "right_record_id": f"b:{i}"}
            for i in range(13)
        ]  # 26 unique records > default 25
        reasons = get_master_commit_block_reasons(
            classification_review=[],
            duplicate_review=reviews,
            canonical=[{"popup_id": "x"}],
            popup_record_count=500,
        )
        self.assertTrue(any(x.startswith("duplicate_quarantine_records=26") for x in reasons))

    def test_review_rate_spike_blocks_even_below_absolute_count(self):
        reviews = [
            {"left_record_id": f"a:{i}", "right_record_id": f"b:{i}"}
            for i in range(5)
        ]  # 10 unique out of 100 = 10%
        reasons = get_master_commit_block_reasons(
            classification_review=[],
            duplicate_review=reviews,
            canonical=[{"popup_id": "x"}],
            popup_record_count=100,
        )
        self.assertTrue(any(x.startswith("duplicate_quarantine_rate=10.0%") for x in reasons))


if __name__ == "__main__":
    unittest.main()
