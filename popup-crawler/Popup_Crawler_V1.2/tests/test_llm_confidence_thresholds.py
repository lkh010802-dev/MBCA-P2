from __future__ import annotations

import unittest

from llm.popup_classifier import confidence_threshold_for, should_auto_apply


class LlmConfidenceThresholdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {
            "threshold": 0.85,
            "non_popup_threshold": 0.70,
        }

    def test_non_popup_uses_relaxed_threshold(self) -> None:
        self.assertEqual(
            0.70,
            confidence_threshold_for("NON_POPUP", self.config),
        )

    def test_popup_and_insufficient_data_keep_strict_threshold(self) -> None:
        self.assertEqual(0.85, confidence_threshold_for("POPUP", self.config))
        self.assertEqual(
            0.85,
            confidence_threshold_for("INSUFFICIENT_DATA", self.config),
        )

    def test_today_non_popup_confidence_is_applied_but_not_as_popup(self) -> None:
        self.assertTrue(should_auto_apply("NON_POPUP", 0.72, self.config))
        self.assertFalse(should_auto_apply("POPUP", 0.72, self.config))


if __name__ == "__main__":
    unittest.main()
