import unittest

from scripts.seed_activity_categories import (
    ACTIVITY_CATEGORIES,
    seed_activity_categories,
)


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class _FakeSession:
    def __init__(self):
        self.categories = {}
        self.commits = 0

    def scalars(self, _statement):
        return _Scalars(self.categories.values())

    def add(self, category):
        self.categories[category.code] = category

    def commit(self):
        self.commits += 1


class SeedActivityCategoriesTests(unittest.TestCase):
    def test_seed_is_idempotent_and_restores_reference_values(self):
        db = _FakeSession()

        seed_activity_categories(db)
        db.categories["food"].name = "변경됨"
        db.categories["food"].is_active = False
        seed_activity_categories(db)

        self.assertEqual(len(db.categories), len(ACTIVITY_CATEGORIES))
        self.assertEqual(db.categories["food"].name, "음식")
        self.assertTrue(db.categories["food"].is_active)
        self.assertEqual(db.commits, 2)


if __name__ == "__main__":
    unittest.main()
