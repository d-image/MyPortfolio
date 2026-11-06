from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


class ContactApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.submissions_file = Path(self.temp_dir.name) / "submissions.jsonl"
        self.settings = Settings(
            app_env="test",
            host="127.0.0.1",
            port=8000,
            allowed_origins=["https://portfolio.example"],
            allowed_hosts=["testserver"],
            force_https=False,
            max_request_size=256,
            contact_rate_limit=1,
            contact_rate_window_seconds=60,
            submissions_file=str(self.submissions_file),
            auth_database_file=str(Path(self.temp_dir.name) / "auth.sqlite3"),
        )
        self.client = TestClient(create_app(self.settings))
        self.payload = {
            "name": "Alex Example",
            "email": "alex@example.com",
            "message": "Please contact me about a project.",
        }

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_valid_contact_is_stored_with_restricted_permissions(self) -> None:
        response = self.client.post(
            "/api/contact",
            json=self.payload,
            headers={"Origin": "https://portfolio.example"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"status": "received"})
        record = json.loads(self.submissions_file.read_text(encoding="utf-8"))
        self.assertEqual(record["email"], self.payload["email"])
        self.assertEqual(record["message"], self.payload["message"])
        if os.name == "posix":
            self.assertEqual(self.submissions_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.submissions_file.parent.stat().st_mode & 0o777, 0o700)

    def test_rejects_untrusted_origin(self) -> None:
        response = self.client.post(
            "/api/contact",
            json=self.payload,
            headers={"Origin": "https://attacker.example"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.submissions_file.exists())

    def test_limits_requests_per_client(self) -> None:
        first = self.client.post("/api/contact", json=self.payload)
        second = self.client.post("/api/contact", json=self.payload)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second.headers)

    def test_invalid_submissions_also_consume_rate_limit(self) -> None:
        invalid = self.client.post(
            "/api/contact",
            json={**self.payload, "email": "not-an-email"},
        )
        valid = self.client.post("/api/contact", json=self.payload)

        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(valid.status_code, 429)

    def test_rejects_oversized_request_body(self) -> None:
        response = self.client.post(
            "/api/contact",
            content=json.dumps({**self.payload, "message": "x" * 1000}),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"detail": "Request body too large"})
        self.assertFalse(self.submissions_file.exists())

    def test_validation_errors_do_not_echo_submitted_values(self) -> None:
        response = self.client.post(
            "/api/contact",
            json={**self.payload, "email": "not-an-email"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("not-an-email", response.text)

    def test_security_headers_are_present(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_rejects_untrusted_host(self) -> None:
        response = self.client.get("/health", headers={"Host": "attacker.example"})

        self.assertEqual(response.status_code, 400)

    def test_production_disables_interactive_api_documentation(self) -> None:
        production_settings = Settings(
            app_env="production",
            host="127.0.0.1",
            port=8000,
            allowed_origins=["https://portfolio.example"],
            allowed_hosts=["api.portfolio.example"],
            force_https=False,
            max_request_size=256,
            contact_rate_limit=1,
            contact_rate_window_seconds=60,
            submissions_file=str(self.submissions_file),
            auth_database_file=str(Path(self.temp_dir.name) / "production-auth.sqlite3"),
        )
        client = TestClient(create_app(production_settings))
        try:
            response = client.get(
                "/docs", headers={"Host": "api.portfolio.example"}
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 404)

    def test_untrusted_host_is_rejected_before_https_redirect(self) -> None:
        https_settings = Settings(
            app_env="test",
            host="127.0.0.1",
            port=8000,
            allowed_origins=["https://portfolio.example"],
            allowed_hosts=["testserver"],
            force_https=True,
            max_request_size=256,
            contact_rate_limit=1,
            contact_rate_window_seconds=60,
            submissions_file=str(self.submissions_file),
            auth_database_file=str(Path(self.temp_dir.name) / "https-auth.sqlite3"),
        )
        client = TestClient(create_app(https_settings), follow_redirects=False)
        try:
            response = client.post(
                "/api/contact",
                json=self.payload,
                headers={"Host": "attacker.example"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("attacker.example", response.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
