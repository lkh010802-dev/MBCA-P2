import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import jwt
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from auth import JWT_ALGORITHM, JWT_SECRET_KEY, hash_password, verify_password
from database import get_db
from db_models import User
from main import app


class AuthApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.valid_password_hash = hash_password("correct-password")

    def setUp(self):
        self.db = Mock()
        app.dependency_overrides[get_db] = lambda: self.db

    def tearDown(self):
        app.dependency_overrides.clear()

    def make_user(self, user_id=1, email="user@example.com"):
        return User(
            id=user_id,
            email=email,
            password_hash=self.valid_password_hash,
            nickname="테스트",
            created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )

    def auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    def encode_token(self, payload):
        return jwt.encode(
            payload,
            JWT_SECRET_KEY,
            algorithm=JWT_ALGORITHM,
        )

    @patch("database.SessionLocal")
    def test_get_db_closes_session(self, mock_session_local):
        session = mock_session_local.return_value
        dependency = get_db()

        self.assertIs(next(dependency), session)
        dependency.close()

        session.close.assert_called_once()

    def test_signup_normalizes_input_and_hashes_password(self):
        self.db.scalar.return_value = None

        def assign_generated_values(user):
            user.id = 1
            user.created_at = datetime(2026, 9, 4, tzinfo=timezone.utc)

        self.db.add.side_effect = assign_generated_values
        response = self.client.post(
            "/auth/signup",
            json={
                "email": "  User@Example.COM  ",
                "password": "password123",
                "nickname": "  코알라  ",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {
                "id": 1,
                "email": "user@example.com",
                "nickname": "코알라",
                "created_at": "2026-09-04T00:00:00Z",
            },
        )
        saved_user = self.db.add.call_args.args[0]
        self.assertNotEqual(saved_user.password_hash, "password123")
        self.assertTrue(verify_password("password123", saved_user.password_hash))
        self.assertNotIn("password_hash", response.json())

    def test_signup_rejects_duplicate_email(self):
        self.db.scalar.return_value = self.make_user()

        response = self.client.post(
            "/auth/signup",
            json={
                "email": " USER@EXAMPLE.COM ",
                "password": "password123",
                "nickname": "코알라",
            },
        )

        self.assertEqual(response.status_code, 409)
        statement = self.db.scalar.call_args.args[0]
        self.assertIn("user@example.com", statement.compile().params.values())
        self.db.add.assert_not_called()

    def test_signup_rolls_back_unique_race(self):
        self.db.scalar.return_value = None
        self.db.commit.side_effect = IntegrityError(
            "duplicate",
            {},
            Exception("duplicate"),
        )

        response = self.client.post(
            "/auth/signup",
            json={
                "email": "user@example.com",
                "password": "password123",
                "nickname": "코알라",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.db.rollback.assert_called_once()

    def test_signup_rejects_invalid_input(self):
        invalid_payloads = [
            {"email": "invalid", "password": "password123", "nickname": "n"},
            {"email": "a@b.com", "password": "short", "nickname": "n"},
            {"email": "a@b.com", "password": "password123", "nickname": "   "},
            {
                "email": "a@b.com",
                "password": "password123",
                "nickname": "n" * 51,
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post("/auth/signup", json=payload)
                self.assertEqual(response.status_code, 422)

    def test_login_success(self):
        self.db.scalar.return_value = self.make_user()

        response = self.client.post(
            "/auth/login",
            json={
                "email": " USER@EXAMPLE.COM ",
                "password": "correct-password",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["token_type"], "bearer")
        self.assertIsInstance(response.json()["access_token"], str)
        statement = self.db.scalar.call_args.args[0]
        self.assertIn("user@example.com", statement.compile().params.values())

    def test_login_failures_do_not_reveal_account_existence(self):
        self.db.scalar.return_value = self.make_user()
        wrong_password = self.client.post(
            "/auth/login",
            json={"email": "user@example.com", "password": "wrong-password"},
        )
        self.db.scalar.return_value = None
        missing_user = self.client.post(
            "/auth/login",
            json={"email": "missing@example.com", "password": "wrong-password"},
        )

        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(missing_user.status_code, 401)
        self.assertEqual(wrong_password.json(), missing_user.json())
        self.assertEqual(
            wrong_password.headers["www-authenticate"],
            "Bearer",
        )

    def test_users_me_with_valid_token(self):
        user = self.make_user()
        self.db.get.return_value = user
        self.db.scalar.return_value = user
        login_response = self.client.post(
            "/auth/login",
            json={"email": user.email, "password": "correct-password"},
        )

        response = self.client.get(
            "/users/me",
            headers=self.auth_header(login_response.json()["access_token"]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], user.email)
        self.assertNotIn("password_hash", response.json())

    def test_users_me_without_token(self):
        response = self.client.get("/users/me")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_users_me_rejects_invalid_token(self):
        response = self.client.get(
            "/users/me",
            headers=self.auth_header("not-a-token"),
        )

        self.assertEqual(response.status_code, 401)

    def test_users_me_rejects_expired_token(self):
        token = self.encode_token({
            "sub": "1",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        })

        response = self.client.get("/users/me", headers=self.auth_header(token))

        self.assertEqual(response.status_code, 401)

    def test_users_me_rejects_missing_sub(self):
        token = self.encode_token({
            "exp": datetime.now(timezone.utc) + timedelta(minutes=1),
        })

        response = self.client.get("/users/me", headers=self.auth_header(token))

        self.assertEqual(response.status_code, 401)

    def test_users_me_rejects_missing_exp(self):
        token = self.encode_token({"sub": "1"})

        response = self.client.get("/users/me", headers=self.auth_header(token))

        self.assertEqual(response.status_code, 401)

    def test_users_me_rejects_invalid_sub(self):
        token = self.encode_token({
            "sub": "not-an-id",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=1),
        })

        response = self.client.get("/users/me", headers=self.auth_header(token))

        self.assertEqual(response.status_code, 401)

    def test_users_me_rejects_deleted_user(self):
        self.db.get.return_value = None
        token = self.encode_token({
            "sub": "999",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=1),
        })

        response = self.client.get("/users/me", headers=self.auth_header(token))

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
