from __future__ import annotations

import unittest
from pathlib import Path

from integration.decisions import apply_classification_decisions
from utils.jsonl import load_jsonl


class V097DecisionTests(unittest.TestCase):
    def test_new_review_decisions_are_present(self):
        decisions = load_jsonl(Path('config/review_decisions.jsonl'))
        by_id = {
            row['record_id']: row
            for row in decisions
            if row.get('decision_type') == 'CLASSIFICATION'
        }
        self.assertEqual(by_id['popply:5874']['classification'], 'NON_POPUP')
        self.assertEqual(by_id['popga:8778']['classification'], 'NON_POPUP')
        self.assertEqual(by_id['popga:8779']['classification'], 'NON_POPUP')

    def test_classification_overrides_conflicting_pairs(self):
        decisions = load_jsonl(Path('config/review_decisions.jsonl'))
        rows = [
            {'record_id':'popply:5874','classification':'POPUP','classification_reasons':[]},
            {'record_id':'popga:8778','classification':'POPUP','classification_reasons':[]},
            {'record_id':'popga:8779','classification':'POPUP','classification_reasons':[]},
        ]
        updated, applied = apply_classification_decisions(rows, decisions)
        self.assertEqual([row['classification'] for row in updated], ['NON_POPUP'] * 3)
        self.assertEqual(len(applied), 3)


if __name__ == '__main__':
    unittest.main()
