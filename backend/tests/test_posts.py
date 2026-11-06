from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


class BlogPostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
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
            auth_rate_limit=20,
            auth_rate_window_seconds=900,
            submissions_file=str(Path(self.temp_dir.name) / "submissions.jsonl"),
            auth_database_file=str(Path(self.temp_dir.name) / "auth.sqlite3"),
        )
        self.client = TestClient(create_app(self.settings))
        self.client.__enter__()
        self.headers = {"Origin": "https://portfolio.example"}

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp_dir.cleanup()

    @staticmethod
    def credentials(email: str) -> dict[str, str]:
        return {
            "email": email,
            "display_name": email.split("@")[0],
            "password": "a secure password",
        }

    def sign_up(self, client: TestClient, email: str) -> dict:
        response = client.post(
            "/api/auth/signup",
            json=self.credentials(email),
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["user"]

    @staticmethod
    def post_payload(title: str = "A useful article") -> dict[str, str]:
        return {
            "title": title,
            "excerpt": "A concise summary of this useful article.",
            "content": "This is the full article body with useful details.",
        }

    def test_signed_in_author_can_publish_edit_and_delete_posts(self) -> None:
        user = self.sign_up(self.client, "author@example.com")
        created = self.client.post(
            "/api/posts", json=self.post_payload(), headers=self.headers
        )

        self.assertEqual(created.status_code, 201)
        post = created.json()["post"]
        self.assertEqual(post["author"], user["displayName"])
        self.assertTrue(post["isMine"])
        self.assertEqual(
            self.client.get("/api/posts").json()["posts"][0]["content"],
            self.post_payload()["content"],
        )

        updated_payload = self.post_payload("An updated article")
        updated_payload["excerpt"] = "The changed summary."
        updated = self.client.put(
            f"/api/posts/{post['id']}",
            json=updated_payload,
            headers=self.headers,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["post"]["title"], "An updated article")
        self.assertEqual(
            self.client.get("/api/posts").json()["posts"][0]["excerpt"],
            "The changed summary.",
        )

        deleted = self.client.delete(
            f"/api/posts/{post['id']}", headers=self.headers
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/posts").json()["posts"], [])

    def test_post_changes_require_sign_in_and_an_allowed_origin(self) -> None:
        unauthorized = self.client.post(
            "/api/posts",
            json=self.post_payload(),
            headers=self.headers,
        )
        self.assertEqual(unauthorized.status_code, 401)

        self.sign_up(self.client, "author@example.com")
        untrusted_origin = self.client.post(
            "/api/posts",
            json=self.post_payload(),
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(untrusted_origin.status_code, 403)
        self.assertEqual(self.client.get("/api/posts").json()["posts"], [])

    def test_authors_cannot_edit_or_delete_another_authors_post(self) -> None:
        self.sign_up(self.client, "first@example.com")
        created = self.client.post(
            "/api/posts", json=self.post_payload(), headers=self.headers
        )
        post_id = created.json()["post"]["id"]

        with TestClient(create_app(self.settings)) as other_client:
            self.sign_up(other_client, "second@example.com")
            edited = other_client.put(
                f"/api/posts/{post_id}",
                json=self.post_payload("Overwritten"),
                headers=self.headers,
            )
            deleted = other_client.delete(
                f"/api/posts/{post_id}", headers=self.headers
            )
            visible_posts = other_client.get("/api/posts").json()["posts"]

        self.assertEqual(edited.status_code, 404)
        self.assertEqual(deleted.status_code, 404)
        self.assertEqual(visible_posts[0]["title"], "A useful article")
        self.assertFalse(visible_posts[0]["isMine"])

    def test_post_validation_rejects_extra_fields_and_overlong_content(self) -> None:
        self.sign_up(self.client, "author@example.com")
        invalid = self.client.post(
            "/api/posts",
            json={**self.post_payload(), "is_admin": True},
            headers=self.headers,
        )
        oversized = self.client.post(
            "/api/posts",
            json={**self.post_payload(), "content": "x" * 20_001},
            headers=self.headers,
        )

        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(oversized.status_code, 422)


if __name__ == "__main__":
    unittest.main()
