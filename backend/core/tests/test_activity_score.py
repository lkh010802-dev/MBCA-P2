import unittest
from unittest.mock import patch

import pandas as pd

from activity_score import (
    _load_poi_activity_scores_cached,
    load_poi_activity_scores,
    load_store_data as original_load_store_data,
)


EXPECTED_COLUMNS = [
    "AREA_CD",
    "AREA_NM",
    "CATEGORY",
    "food_count",
    "cafe_count",
    "drink_count",
    "entertainment_count",
    "food_score",
    "cafe_score",
    "drink_score",
    "entertainment_score",
    "walk_score",
    "culture_score",
    "shopping_score",
]


class ActivityScoreCacheTests(unittest.TestCase):
    def setUp(self):
        _load_poi_activity_scores_cached.cache_clear()

    def tearDown(self):
        _load_poi_activity_scores_cached.cache_clear()

    def test_same_input_is_calculated_once(self):
        with patch(
            "activity_score.load_store_data",
            wraps=original_load_store_data,
        ) as mock_load_store_data:
            load_poi_activity_scores()
            load_poi_activity_scores()

        mock_load_store_data.assert_called_once()

    def test_returned_dataframe_does_not_mutate_cached_result(self):
        first = load_poi_activity_scores()
        original_name = first.loc[0, "AREA_NM"]
        first.loc[0, "AREA_NM"] = "변경된 값"

        second = load_poi_activity_scores()

        self.assertEqual(second.loc[0, "AREA_NM"], original_name)

    def test_cache_clear_recalculates_result(self):
        with patch(
            "activity_score.load_store_data",
            wraps=original_load_store_data,
        ) as mock_load_store_data:
            first = load_poi_activity_scores()
            _load_poi_activity_scores_cached.cache_clear()
            recalculated = load_poi_activity_scores()

        self.assertEqual(mock_load_store_data.call_count, 2)
        pd.testing.assert_frame_equal(first, recalculated)

    def test_existing_result_shape_columns_and_scores_are_preserved(self):
        first = load_poi_activity_scores()
        second = load_poi_activity_scores()

        self.assertEqual(len(first), 121)
        self.assertEqual(list(first.columns), EXPECTED_COLUMNS)
        pd.testing.assert_frame_equal(first, second)


if __name__ == "__main__":
    unittest.main()
