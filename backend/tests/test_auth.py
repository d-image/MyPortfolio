from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


class BlogAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = Path(self.temp_dir.name) / "auth.sqlite3"
        self.settings = Settings(
            app_env="test",
            host="127.0.0.1",
            port=8000,
            allowed_origins=["https://portfolio.example"],
            allowed_hosts=["testserver"],
            force_https=False,
            max_request_size=1_048_576,
            contact_rate_limit=5,
            contact_rate_window_seconds=300,
            auth_rate_limit=10,
            auth_rate_window_seconds=900,
            submissions_file=str(Path(self.temp_dir.name) / "submissions.jsonl"),
            auth_database_file=str(self.database_file),
        )
        self.client = TestClient(create_app(self.settings))
        self.client.__enter__()
        self.headers = {"Origin": "https://portfolio.example"}

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_signup_creates_user_and_http_only_session(self) -> None:
        response = self.client.post(
            "/api/auth/signup",
            json={"email": "Reader@Example.com", "password": "a secure password"},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["user"]["email"], "reader@example.com")
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        self.assertIn("samesite=lax", response.headers["set-cookie"].lower())
        self.assertNotIn("a secure password", response.text)

        database = sqlite3.connect(self.database_file)
        try:
            row = database.execute(
                "SELECT email, password_hash FROM users"
            ).fetchone()
        finally:
            database.close()
        self.assertEqual(row[0], "reader@example.com")
        self.assertTrue(row[1].startswith("scrypt$"))
        self.assertNotEqual(row[1], "a secure password")
        if os.name == "posix":
            self.assertEqual(self.database_file.stat().st_mode & 0o777, 0o600)

        current_user = self.client.get("/api/auth/me")
        self.assertEqual(current_user.status_code, 200)
        self.assertEqual(current_user.json()["user"]["email"], "reader@example.com")

    def test_duplicate_email_is_case_insensitive(self) -> None:
        first = self.client.post(
            "/api/auth/signup",
            json={"email": "reader@example.com", "password": "a secure password"},
            headers=self.headers,
        )
        duplicate = self.client.post(
            "/api/auth/signup",
            json={"email": "READER@example.com", "password": "another secure pass"},
            headers=self.headers,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(duplicate.status_code, 409)

    def test_login_and_logout_revoke_session(self) -> None:
        self.client.post(
            "/api/auth/signup",
            json={"email": "reader@example.com", "password": "a secure password"},
            headers=self.headers,
        )
        self.client.cookies.clear()

        login = self.client.post(
            "/api/auth/login",
            json={"email": "READER@example.com", "password": "a secure password"},
            headers=self.headers,
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

        logout = self.client.post("/api/auth/logout", headers=self.headers)
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_invalid_credentials_do_not_disclose_account_existence(self) -> None:
        missing_user = self.client.post(
            "/api/auth/login",
            json={"email": "missing@example.com", "password": "a secure password"},
            headers=self.headers,
        )
        self.client.post(
            "/api/auth/signup",
            json={"email": "reader@example.com", "password": "a secure password"},
            headers=self.headers,
        )
        self.client.cookies.clear()
        wrong_password = self.client.post(
            "/api/auth/login",
            json={"email": "reader@example.com", "password": "not the right password"},
            headers=self.headers,
        )

        self.assertEqual(missing_user.status_code, 401)
        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(missing_user.json(), wrong_password.json())

    def test_auth_mutations_require_an_allowed_origin(self) -> None:
        rejected = self.client.post(
            "/api/auth/signup",
            json={"email": "reader@example.com", "password": "a secure password"},
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertFalse(self.client.cookies)

    def test_signup_enforces_password_length(self) -> None:
        response = self.client.post(
            "/api/auth/signup",
            json={"email": "reader@example.com", "password": "short"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('"input"', response.text)

    def test_auth_rate_limit_applies_to_failed_login_attempts(self) -> None:
        limited_settings = Settings(
            **{
                **self.settings.__dict__,
                "auth_rate_limit": 2,
                "auth_rate_window_seconds": 60,
                "auth_database_file": str(Path(self.temp_dir.name) / "limited.sqlite3"),
            }
        )
        with TestClient(create_app(limited_settings)) as client:
            results = [
                client.post(
                    "/api/auth/login",
                    json={"email": "reader@example.com", "password": "wrong password"},
                    headers=self.headers,
                )
                for _ in range(3)
            ]

        self.assertEqual([result.status_code for result in results], [401, 401, 429])
        self.assertIn("Retry-After", results[-1].headers)

    def test_production_session_cookie_is_secure(self) -> None:
        production_settings = Settings(
            app_env="production",
            host="127.0.0.1",
            port=8000,
            allowed_origins=["https://portfolio.example"],
            allowed_hosts=["api.portfolio.example"],
            force_https=False,
            max_request_size=1_048_576,
            contact_rate_limit=5,
            contact_rate_window_seconds=300,
            submissions_file=str(Path(self.temp_dir.name) / "prod-submissions.jsonl"),
            auth_database_file=str(Path(self.temp_dir.name) / "prod-auth.sqlite3"),
        )
        with TestClient(create_app(production_settings)) as client:
            response = client.post(
                "/api/auth/signup",
                json={"email": "reader@example.com", "password": "a secure password"},
                headers={"Host": "api.portfolio.example", **self.headers},
            )

        self.assertEqual(response.status_code, 201)
        self.assertIn("secure", response.headers["set-cookie"].lower())

        if os.name == "posix":
            self.assertEqual(
                (Path(self.temp_dir.name) / "prod-auth.sqlite3").stat().st_mode
                & 0o777,
                0o600,
            )


if __name__ == "__main__":
    unittest.main()
