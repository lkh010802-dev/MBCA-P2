import unittest
from run_integrate import (
    get_master_commit_block_reasons,
    DEFAULT_MAX_CLASSIFICATION_REVIEW_COMMIT,
    DEFAULT_MAX_DUPLICATE_REVIEW_COMMIT,
)

class DuplicateReviewToleranceV2Test(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(DEFAULT_MAX_CLASSIFICATION_REVIEW_COMMIT, 2)
        self.assertEqual(DEFAULT_MAX_DUPLICATE_REVIEW_COMMIT, 10)

    def test_five_duplicate_reviews_are_warning_only(self):
        reasons = get_master_commit_block_reasons(
            classification_review=[{}],
            duplicate_review=[{} for _ in range(5)],
            canonical=[{"popup_id": "x"}],
        )
        self.assertEqual(reasons, [])

    def test_eleven_duplicate_reviews_block(self):
        reasons = get_master_commit_block_reasons(
            classification_review=[{}],
            duplicate_review=[{} for _ in range(11)],
            canonical=[{"popup_id": "x"}],
        )
        self.assertIn("duplicate_review=11 > allowed=10", reasons)

    def test_three_classification_reviews_still_block(self):
        reasons = get_master_commit_block_reasons(
            classification_review=[{}, {}, {}],
            duplicate_review=[],
            canonical=[{"popup_id": "x"}],
        )
        self.assertIn("classification_review=3 > allowed=2", reasons)

if __name__ == "__main__":
    unittest.main()
