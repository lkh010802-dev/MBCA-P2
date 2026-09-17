import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import jwt
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from auth import JWT_ALGORITHM, JWT_SECRET_KEY, create_access_token
from database import get_db
from db_models import User, UserActivityPreference, UserPreference
from main import app
from region_recommendation_service import _calculate_activity_match_score


def intent(**overrides):
    result = {
        "start_location_text": None,
        "target_location_text": None,
        "target_location_scope": None,
        "end_location_text": None,
        "start_time": "12:00",
        "end_time": None,
        "activities": ["cafe"],
        "transport_mode": "auto",
        "space_preference": None,
    }
    result.update(overrides)
    return result


def candidates_and_scores():
    candidates = [
        {
            "AREA_CD": "A",
            "AREA_NM": "지역 A",
            "CATEGORY": "발달상권",
            "latitude": 37.50,
            "longitude": 127.00,
        },
        {
            "AREA_CD": "B",
            "AREA_NM": "지역 B",
            "CATEGORY": "발달상권",
            "latitude": 37.51,
            "longitude": 127.01,
        },
    ]
    scores = pd.DataFrame([
        {
            **candidate,
            "food_score": 1,
            "cafe_score": score,
            "drink_score": 1,
            "entertainment_score": 1,
            "walk_score": 1,
            "culture_score": 1,
            "shopping_score": 1,
        }
        for candidate, score in zip(candidates, (4, 3))
    ])
    return candidates, scores


class RecommendPreferencesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.db = Mock()
        self.user = User(
            id=1,
            email="user@example.com",
            password_hash="not-returned",
            nickname="사용자",
        )
        self.db.get.return_value = self.user
        self.db.scalar.return_value = None
        self.db.execute.return_value.all.return_value = []
        app.dependency_overrides[get_db] = lambda: self.db

    def tearDown(self):
        app.dependency_overrides.clear()

    @staticmethod
    def auth_header(token=None):
        return {
            "Authorization": f"Bearer {token or create_access_token(1)}"
        }

    def call_recommend(self, parsed_intent=None, headers=None):
        candidates, scores = candidates_and_scores()
        with (
            patch(
                "main.parse_user_intent",
                return_value=parsed_intent or intent(),
            ),
            patch("main.load_poi_candidates", return_value=candidates),
            patch("main.load_poi_activity_scores", return_value=scores),
            patch(
                "main.get_travel",
                return_value={"mode": "walk", "duration_min": 20},
            ) as travel,
            patch("main.get_congestion_data", return_value=None),
            patch("main.generate_recommendation_message", return_value="추천"),
            patch("main.find_proactive_suggestion", return_value=None) as proactive,
        ):
            response = self.client.post(
                "/recommend",
                json={
                    "user_message": "근처 카페 추천",
                    "gps_latitude": 37.0,
                    "gps_longitude": 126.0,
                },
                headers=headers,
            )
        return response, travel, proactive

    def set_preferences(
        self,
        *,
        space="indoor",
        transport="walk",
        activities=None,
    ):
        self.db.scalar.return_value = UserPreference(
            user_id=self.user.id,
            space_preference=space,
            transport_mode=transport,
        )
        self.db.execute.return_value.all.return_value = [
            (
                UserActivityPreference(
                    user_id=self.user.id,
                    activity_id=index,
                    preference_level=level,
                ),
                code,
            )
            for index, (code, level) in enumerate(
                (activities or {}).items(),
                start=1,
            )
        ]

    def test_anonymous_request_keeps_existing_behavior_without_preference_query(self):
        response, travel, proactive = self.call_recommend()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["recommendation_context"]["transport_mode"],
            "auto",
        )
        self.assertIsNone(
            response.json()["recommendation_context"]["space_preference"]
        )
        self.assertEqual(
            response.json()["recommendation_context"]["activity_preferences"],
            {},
        )
        self.assertEqual(
            [area["AREA_CD"] for area in response.json()["other_areas"]],
            ["A", "B"],
        )
        self.db.get.assert_not_called()
        self.db.scalar.assert_not_called()
        self.db.execute.assert_not_called()
        self.assertTrue(all(
            call.kwargs["transport_mode"] == "auto"
            for call in travel.call_args_list
        ))
        self.assertEqual(proactive.call_args.kwargs["transport_mode"], "auto")

    def test_authenticated_saved_preferences_fill_missing_values(self):
        self.set_preferences(activities={"cafe": 5})

        response, travel, proactive = self.call_recommend(
            headers=self.auth_header()
        )

        self.assertEqual(response.status_code, 200)
        context = response.json()["recommendation_context"]
        self.assertEqual(context["space_preference"], "indoor")
        self.assertEqual(context["transport_mode"], "walk")
        self.assertEqual(context["activities"], ["cafe"])
        self.assertEqual(context["activity_preferences"], {"cafe": 5})
        self.assertEqual(
            response.json()["other_areas"][0]["activity_match_score"],
            4.2,
        )
        self.assertTrue(all(
            call.kwargs["transport_mode"] == "walk"
            for call in travel.call_args_list
        ))
        self.assertEqual(proactive.call_args.kwargs["transport_mode"], "walk")

    def test_explicit_request_values_override_database_preferences(self):
        self.set_preferences(space="indoor", transport="walk")

        for mode in ("walk", "car", "public_transit"):
            with self.subTest(mode=mode):
                response, travel, proactive = self.call_recommend(
                    intent(space_preference="outdoor", transport_mode=mode),
                    self.auth_header(),
                )

                context = response.json()["recommendation_context"]
                self.assertEqual(context["space_preference"], "outdoor")
                self.assertEqual(context["transport_mode"], mode)
                self.assertTrue(all(
                    call.kwargs["transport_mode"] == mode
                    for call in travel.call_args_list
                ))
                self.assertEqual(
                    proactive.call_args.kwargs["transport_mode"],
                    mode,
                )

    def test_authenticated_user_without_saved_preferences_is_unchanged(self):
        response, _, _ = self.call_recommend(headers=self.auth_header())

        self.assertEqual(response.status_code, 200)
        context = response.json()["recommendation_context"]
        self.assertEqual(context["transport_mode"], "auto")
        self.assertIsNone(context["space_preference"])
        self.assertEqual(context["activity_preferences"], {})
        self.assertEqual(
            response.json()["other_areas"][0]["activity_match_score"],
            4.0,
        )

    def test_unrequested_activity_preference_is_ignored(self):
        self.set_preferences(activities={"food": 5})

        response, _, proactive = self.call_recommend(
            headers=self.auth_header()
        )

        self.assertEqual(
            response.json()["recommendation_context"]["activities"],
            ["cafe"],
        )
        self.assertEqual(
            response.json()["recommendation_context"]["activity_preferences"],
            {},
        )
        self.assertEqual(
            response.json()["other_areas"][0]["activity_match_score"],
            4.0,
        )
        self.assertEqual(proactive.call_args.kwargs["activities"], ["cafe"])

    def test_database_error_falls_back_to_non_personalized_recommendation(self):
        self.db.scalar.side_effect = SQLAlchemyError("read failed")

        response, _, _ = self.call_recommend(headers=self.auth_header())

        self.assertEqual(response.status_code, 200)
        context = response.json()["recommendation_context"]
        self.assertEqual(context["transport_mode"], "auto")
        self.assertIsNone(context["space_preference"])
        self.db.rollback.assert_called_once()

    def test_invalid_and_expired_tokens_return_401(self):
        expired = jwt.encode(
            {
                "sub": "1",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            JWT_SECRET_KEY,
            algorithm=JWT_ALGORITHM,
        )

        for token in ("invalid", expired):
            with self.subTest(token=token):
                response, _, _ = self.call_recommend(
                    headers=self.auth_header(token)
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_token_for_missing_user_returns_401(self):
        self.db.get.return_value = None

        response, _, _ = self.call_recommend(headers=self.auth_header())

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.db.scalar.assert_not_called()

    def test_preference_query_is_scoped_to_authenticated_user(self):
        response, _, _ = self.call_recommend(headers=self.auth_header())

        self.assertEqual(response.status_code, 200)
        scalar_values = self.db.scalar.call_args.args[0].compile().params.values()
        execute_values = self.db.execute.call_args.args[0].compile().params.values()
        self.assertIn(self.user.id, scalar_values)
        self.assertIn(self.user.id, execute_values)

    def test_activity_preference_bonus_policy_and_clamp(self):
        candidate = {"cafe_score": 4.0}
        expected = {1: 4.0, 2: 4.0, 3: 4.0, 4: 4.1, 5: 4.2}

        for level, score in expected.items():
            with self.subTest(level=level):
                self.assertEqual(
                    _calculate_activity_match_score(
                        candidate,
                        ["cafe"],
                        {"cafe": level},
                    ),
                    score,
                )

        self.assertEqual(
            _calculate_activity_match_score(
                {"cafe_score": 4.9},
                ["cafe"],
                {"cafe": 5},
            ),
            5.0,
        )
        self.assertEqual(
            _calculate_activity_match_score(
                {"cafe_score": 4.0, "food_score": 1.0},
                ["cafe"],
                {"food": 5},
            ),
            4.0,
        )


if __name__ == "__main__":
    unittest.main()
