import unittest

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from auth import create_access_token
from database import get_db
from db_models import (
    ActivityCategory,
    User,
    UserActivityPreference,
    UserPreference,
)
from main import app


ACTIVITY_CODES = (
    "food",
    "cafe",
    "walk",
    "culture",
    "entertainment",
    "shopping",
    "drink",
)


class _Result:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class FakeSession:
    def __init__(self, users):
        self.users = {user.id: user for user in users}
        self.preferences = []
        self.categories = [
            ActivityCategory(
                id=index,
                code=code,
                name=code,
                is_active=True,
            )
            for index, code in enumerate(ACTIVITY_CODES, start=1)
        ]
        self.activity_preferences = []
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_commit = False

    @staticmethod
    def _params(statement):
        return list(statement.compile().params.values())

    @classmethod
    def _single_int(cls, statement):
        return next(value for value in cls._params(statement) if type(value) is int)

    @classmethod
    def _list_param(cls, statement):
        return next(value for value in cls._params(statement) if isinstance(value, list))

    def get(self, model, identity):
        return self.users.get(identity) if model is User else None

    def scalar(self, statement):
        model = statement.column_descriptions[0]["entity"]
        if model is UserPreference:
            user_id = self._single_int(statement)
            return next(
                (item for item in self.preferences if item.user_id == user_id),
                None,
            )
        raise AssertionError(f"unexpected scalar query: {statement}")

    def scalars(self, statement):
        model = statement.column_descriptions[0]["entity"]
        if model is ActivityCategory:
            codes = set(self._list_param(statement))
            return _Result(
                item for item in self.categories if item.code in codes
            )
        if model is UserActivityPreference:
            user_id = self._single_int(statement)
            activity_ids = set(self._list_param(statement))
            return _Result(
                item
                for item in self.activity_preferences
                if item.user_id == user_id and item.activity_id in activity_ids
            )
        raise AssertionError(f"unexpected scalars query: {statement}")

    def execute(self, statement):
        user_id = self._single_int(statement)
        categories = {item.id: item for item in self.categories if item.is_active}
        return _Result(
            (item, categories[item.activity_id].code)
            for item in self.activity_preferences
            if item.user_id == user_id and item.activity_id in categories
        )

    def add(self, item):
        if isinstance(item, UserPreference):
            self.preferences.append(item)
        elif isinstance(item, UserActivityPreference):
            self.activity_preferences.append(item)
        else:
            raise AssertionError(f"unexpected add: {item}")

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise SQLAlchemyError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class UserPreferencesApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.user = User(
            id=1,
            email="user@example.com",
            password_hash="not-returned",
            nickname="사용자",
        )
        self.other_user = User(
            id=2,
            email="other@example.com",
            password_hash="not-returned",
            nickname="다른 사용자",
        )
        self.db = FakeSession([self.user, self.other_user])
        self.headers = {
            "Authorization": f"Bearer {create_access_token(self.user.id)}"
        }
        app.dependency_overrides[get_db] = lambda: self.db

    def tearDown(self):
        app.dependency_overrides.clear()

    def request(self, method, payload=None, headers=None):
        return self.client.request(
            method,
            "/users/me/preferences",
            json=payload,
            headers=self.headers if headers is None else headers,
        )

    def test_get_empty_preferences(self):
        response = self.request("GET")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "space_preference": None,
                "transport_mode": None,
                "activity_preferences": [],
            },
        )

    def test_get_basic_and_activity_preferences_in_stable_order(self):
        self.db.preferences.append(
            UserPreference(
                user_id=self.user.id,
                space_preference="indoor",
                transport_mode="walk",
            )
        )
        self.db.activity_preferences.extend(
            [
                UserActivityPreference(
                    user_id=self.user.id,
                    activity_id=7,
                    preference_level=3,
                ),
                UserActivityPreference(
                    user_id=self.user.id,
                    activity_id=1,
                    preference_level=5,
                ),
            ]
        )

        response = self.request("GET")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["space_preference"], "indoor")
        self.assertEqual(response.json()["transport_mode"], "walk")
        self.assertEqual(
            response.json()["activity_preferences"],
            [
                {"activity": "food", "preference_level": 5},
                {"activity": "drink", "preference_level": 3},
            ],
        )
        self.assertNotIn("password_hash", response.text)

    def test_get_does_not_expose_another_users_preferences(self):
        self.db.preferences.append(
            UserPreference(
                user_id=self.other_user.id,
                space_preference="outdoor",
                transport_mode="car",
            )
        )
        self.db.activity_preferences.append(
            UserActivityPreference(
                user_id=self.other_user.id,
                activity_id=1,
                preference_level=5,
            )
        )

        response = self.request("GET")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["space_preference"])
        self.assertEqual(response.json()["activity_preferences"], [])

    def test_first_save_and_existing_value_update(self):
        first = self.request(
            "PUT",
            {
                "space_preference": "indoor",
                "transport_mode": "public_transit",
                "activity_preferences": [
                    {"activity": "cafe", "preference_level": 4}
                ],
            },
        )
        second = self.request(
            "PUT",
            {
                "space_preference": "outdoor",
                "activity_preferences": [
                    {"activity": "cafe", "preference_level": 5}
                ],
            },
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["space_preference"], "outdoor")
        self.assertEqual(second.json()["transport_mode"], "public_transit")
        self.assertEqual(
            second.json()["activity_preferences"],
            [{"activity": "cafe", "preference_level": 5}],
        )
        self.assertEqual(len(self.db.preferences), 1)
        self.assertEqual(len(self.db.activity_preferences), 1)
        self.assertEqual(self.db.commit_count, 2)

    def test_partial_activity_update_preserves_other_activities(self):
        self.request(
            "PUT",
            {
                "activity_preferences": [
                    {"activity": "food", "preference_level": 2},
                    {"activity": "walk", "preference_level": 3},
                ]
            },
        )

        response = self.request(
            "PUT",
            {
                "activity_preferences": [
                    {"activity": "walk", "preference_level": 5}
                ]
            },
        )

        self.assertEqual(
            response.json()["activity_preferences"],
            [
                {"activity": "food", "preference_level": 2},
                {"activity": "walk", "preference_level": 5},
            ],
        )

    def test_explicit_null_clears_basic_preferences(self):
        self.db.preferences.append(
            UserPreference(
                user_id=self.user.id,
                space_preference="indoor",
                transport_mode="car",
            )
        )

        response = self.request(
            "PUT",
            {"space_preference": None, "transport_mode": None},
        )

        self.assertIsNone(response.json()["space_preference"])
        self.assertIsNone(response.json()["transport_mode"])

    def test_empty_activity_list_and_omitted_fields_preserve_values(self):
        self.db.preferences.append(
            UserPreference(
                user_id=self.user.id,
                space_preference="indoor",
                transport_mode="walk",
            )
        )
        self.db.activity_preferences.append(
            UserActivityPreference(
                user_id=self.user.id,
                activity_id=1,
                preference_level=4,
            )
        )

        response = self.request("PUT", {"activity_preferences": []})

        self.assertEqual(response.json()["space_preference"], "indoor")
        self.assertEqual(response.json()["transport_mode"], "walk")
        self.assertEqual(
            response.json()["activity_preferences"],
            [{"activity": "food", "preference_level": 4}],
        )

    def test_authentication_failures(self):
        missing = self.request("GET", headers={})
        invalid = self.request(
            "GET",
            headers={"Authorization": "Bearer invalid"},
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(missing.headers["www-authenticate"], "Bearer")

    def test_invalid_request_values_return_422(self):
        invalid_payloads = [
            {"activity_preferences": [{"activity": "food", "preference_level": 0}]},
            {"activity_preferences": [{"activity": "food", "preference_level": 6}]},
            {"activity_preferences": [{"activity": "invalid", "preference_level": 3}]},
            {
                "activity_preferences": [
                    {"activity": "food", "preference_level": 3},
                    {"activity": "food", "preference_level": 4},
                ]
            },
            {"space_preference": "inside"},
            {"transport_mode": "bicycle"},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.request("PUT", payload)
                self.assertEqual(response.status_code, 422)

    def test_missing_or_inactive_category_is_rejected_without_commit(self):
        self.db.categories = [
            item for item in self.db.categories if item.code != "drink"
        ]
        missing = self.request(
            "PUT",
            {"activity_preferences": [{"activity": "drink", "preference_level": 3}]},
        )
        food = next(item for item in self.db.categories if item.code == "food")
        food.is_active = False
        inactive = self.request(
            "PUT",
            {"activity_preferences": [{"activity": "food", "preference_level": 3}]},
        )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(inactive.status_code, 400)
        self.assertEqual(self.db.commit_count, 0)

    def test_database_error_rolls_back(self):
        self.db.fail_commit = True

        response = self.request("PUT", {"space_preference": "indoor"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "취향 정보를 저장하지 못했습니다.")
        self.assertEqual(self.db.commit_count, 1)
        self.assertEqual(self.db.rollback_count, 1)


if __name__ == "__main__":
    unittest.main()
