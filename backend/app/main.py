from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from collections.abc import AsyncIterator
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings, settings

logger = logging.getLogger(__name__)


class ContactSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr = Field(max_length=254)
    message: str = Field(min_length=10, max_length=5000)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError("Name contains invalid characters")
        return value

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if any(
                (ord(char) < 32 and char not in "\t\n\r") or ord(char) == 127
                for char in value
            ):
                raise ValueError("Message contains invalid characters")
        return value


class SignUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(default="Blog author", min_length=1, max_length=60)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError("Display name contains invalid characters")
        return value


class BlogPostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    excerpt: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=10, max_length=20_000)

    @field_validator("title", "excerpt", "content", mode="before")
    @classmethod
    def normalize_post_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if any(
                (ord(char) < 32 and char not in "\t\n\r") or ord(char) == 127
                for char in value
            ):
                raise ValueError("Text contains invalid characters")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class RequestSizeLimitMiddleware:
    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_headers = scope.get("headers", [])
        content_lengths = [
            value for name, value in raw_headers if name.lower() == b"content-length"
        ]
        has_transfer_encoding = any(
            name.lower() == b"transfer-encoding" for name, _ in raw_headers
        )
        if len(content_lengths) > 1 or (content_lengths and has_transfer_encoding):
            await self._reject(send, 400, "Invalid request framing")
            return
        if content_lengths:
            try:
                declared_size = int(content_lengths[0])
            except ValueError:
                await self._reject(send, 400, "Invalid Content-Length")
                return
            if declared_size < 0:
                await self._reject(send, 400, "Invalid Content-Length")
                return
            if declared_size > self.max_bytes:
                await self._reject(send, 413, "Request body too large")
                return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await self._reject(send, 413, "Request body too large")
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        buffered_body = b"".join(chunks)
        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {
                    "type": "http.request",
                    "body": buffered_body,
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(send: Any, status_code: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def add_security_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"permissions-policy",
                            b"camera=(), microphone=(), geolocation=()",
                        ),
                        (b"cache-control", b"no-store"),
                    ]
                )
                path = scope.get("path", "")
                if path.startswith("/api/"):
                    headers.append(
                        (
                            b"content-security-policy",
                            b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
                        )
                    )
                if scope.get("scheme") == "https":
                    headers.append(
                        (
                            b"strict-transport-security",
                            b"max-age=31536000; includeSubDomains",
                        )
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, add_security_headers)


class ContactRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_clients = 10_000

    def consume(self, client_key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            expired_before = now - self.window_seconds
            for key in list(self._requests):
                requests = self._requests[key]
                while requests and requests[0] <= expired_before:
                    requests.popleft()
                if not requests:
                    del self._requests[key]

            if client_key not in self._requests and len(self._requests) >= self._max_clients:
                return False, self.window_seconds

            requests = self._requests[client_key]
            if len(requests) >= self.limit:
                retry_after = max(
                    1,
                    int(self.window_seconds - (now - requests[0]) + 0.999),
                )
                return False, retry_after

            requests.append(now)
            return True, 0


class ContactRequestGuardMiddleware:
    def __init__(
        self,
        app: Any,
        limiter: ContactRateLimiter,
        allowed_origins: list[str],
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/api/contact"
        ):
            origins = [
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name.lower() == b"origin"
            ]
            if len(origins) > 1 or (
                origins and origins[0] not in self.allowed_origins
            ):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Origin not allowed"},
                )
                await response(scope, receive, send)
                return

            client = scope.get("client")
            client_key = client[0] if client else "unknown"
            allowed, retry_after = self.limiter.consume(client_key)
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many contact submissions"},
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


class AuthRequestGuardMiddleware:
    def __init__(
        self,
        app: Any,
        limiter: ContactRateLimiter,
        allowed_origins: list[str],
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        method = scope.get("method")
        is_auth_mutation = method == "POST" and path in {
            "/api/auth/signup",
            "/api/auth/login",
            "/api/auth/logout",
        }
        is_post_mutation = (
            path == "/api/posts"
            or (path.startswith("/api/posts/") and path.removeprefix("/api/posts/").isdigit())
        ) and method in {"POST", "PUT", "DELETE"}
        if scope["type"] == "http" and (is_auth_mutation or is_post_mutation):
            origins = [
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name.lower() == b"origin"
            ]
            if len(origins) != 1 or origins[0] not in self.allowed_origins:
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Origin not allowed"},
                )
                await response(scope, receive, send)
                return

            client = scope.get("client")
            client_key = client[0] if client else "unknown"
            allowed, retry_after = self.limiter.consume(client_key)
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many account or post requests"},
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def _submission_path(config: Settings) -> Path:
    path = Path(config.submissions_file).expanduser()
    if not path.is_absolute():
        project_root = Path(__file__).resolve().parents[2]
        path = project_root / path
    return path


def _store_submission(config: Settings, submission: ContactSubmission) -> None:
    path = _submission_path(config)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(path.parent, 0o700)

    record = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "name": submission.name,
        "email": str(submission.email),
        "message": submission.message,
    }
    encoded_record = (
        json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "ab") as output:
            descriptor = -1
            output.write(encoded_record)
            output.flush()
            os.fsync(output.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _auth_database_path(config: Settings) -> Path:
    path = Path(config.auth_database_file).expanduser()
    if not path.is_absolute():
        project_root = Path(__file__).resolve().parents[2]
        path = project_root / path
    return path


def _connect_auth_database(config: Settings) -> sqlite3.Connection:
    path = _auth_database_path(config)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if os.name == "posix":
            os.chmod(path, 0o600)
    else:
        os.close(descriptor)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize_auth_database(config: Settings) -> None:
    connection = _connect_auth_database(config)
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                display_name TEXT NOT NULL DEFAULT 'Blog author',
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS blog_posts (
                id INTEGER PRIMARY KEY,
                author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                excerpt TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS blog_posts_created_idx ON blog_posts(created_at DESC);
            """
        )
        user_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(users)")
        }
        if "display_name" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT 'Blog author'"
            )
    finally:
        connection.close()


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
    )
    salt_value = base64.urlsafe_b64encode(salt).decode("ascii")
    hash_value = base64.urlsafe_b64encode(derived).decode("ascii")
    return f"scrypt$16384$8$1${salt_value}${hash_value}"


def _verify_password(password: str, encoded_hash: str | None) -> bool:
    if encoded_hash is None:
        salt = bytes(16)
        expected = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
        )
        hmac.compare_digest(expected, bytes(64))
        return False
    try:
        algorithm, n_value, r_value, p_value, salt_value, hash_value = (
            encoded_hash.split("$")
        )
        if (algorithm, n_value, r_value, p_value) != ("scrypt", "16384", "8", "1"):
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(hash_value.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _user_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "displayName": row["display_name"],
        "createdAt": row["created_at"],
    }


def _issue_session(connection: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    now = int(time.time())
    with connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        connection.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user_id, now + 7 * 24 * 60 * 60),
        )
    return token


def _session_token_hash(token: str | None) -> str | None:
    if token is None or len(token) != 43:
        return None
    allowed_characters = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    if any(char not in allowed_characters for char in token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _register_user(
    config: Settings, email: str, password: str, display_name: str
) -> tuple[dict[str, Any], str] | None:
    password_hash = _hash_password(password)
    connection = _connect_auth_database(config)
    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO users (email, display_name, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    email,
                    display_name,
                    password_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            user_id = cursor.lastrowid
            if user_id is None:
                raise RuntimeError("Unable to create user")
            user = connection.execute(
                "SELECT id, email, display_name, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                raise RuntimeError("Unable to read newly created user")
            token = _issue_session(connection, user_id)
        return _user_record(user), token
    except sqlite3.IntegrityError:
        return None
    finally:
        connection.close()


def _login_user(
    config: Settings, email: str, password: str
) -> tuple[dict[str, Any], str] | None:
    connection = _connect_auth_database(config)
    try:
        user = connection.execute(
            """
            SELECT id, email, display_name, password_hash, created_at
            FROM users WHERE email = ?
            """,
            (email,),
        ).fetchone()
        if not _verify_password(password, user["password_hash"] if user else None):
            return None
        token = _issue_session(connection, user["id"])
        return _user_record(user), token
    finally:
        connection.close()


def _resolve_session(config: Settings, token: str | None) -> dict[str, Any] | None:
    token_hash = _session_token_hash(token)
    if token_hash is None:
        return None
    connection = _connect_auth_database(config)
    try:
        row = connection.execute(
            """
            SELECT users.id, users.email, users.display_name, users.created_at
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (token_hash, int(time.time())),
        ).fetchone()
        return _user_record(row) if row else None
    finally:
        connection.close()


def _revoke_session(config: Settings, token: str | None) -> None:
    token_hash = _session_token_hash(token)
    if token_hash is None:
        return
    connection = _connect_auth_database(config)
    try:
        with connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    finally:
        connection.close()


def _list_blog_posts(
    config: Settings, user_id: int | None
) -> list[dict[str, Any]]:
    connection = _connect_auth_database(config)
    try:
        rows = connection.execute(
            """
            SELECT blog_posts.id, blog_posts.author_id, blog_posts.title,
                   blog_posts.excerpt, blog_posts.content, blog_posts.created_at,
                   blog_posts.updated_at, users.display_name AS author_name
            FROM blog_posts
            JOIN users ON users.id = blog_posts.author_id
            ORDER BY blog_posts.created_at DESC, blog_posts.id DESC
            """
        ).fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "excerpt": row["excerpt"],
                "content": row["content"],
                "author": row["author_name"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "isMine": row["author_id"] == user_id if user_id else False,
            }
            for row in rows
        ]
    finally:
        connection.close()


def _create_blog_post(
    config: Settings, author_id: int, post: BlogPostRequest
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    connection = _connect_auth_database(config)
    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO blog_posts
                    (author_id, title, excerpt, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (author_id, post.title, post.excerpt, post.content, now, now),
            )
            post_id = cursor.lastrowid
            if post_id is None:
                raise RuntimeError("Unable to create blog post")
            row = connection.execute(
                """
                SELECT blog_posts.id, blog_posts.title, blog_posts.excerpt,
                       blog_posts.content, blog_posts.created_at,
                       blog_posts.updated_at, users.display_name AS author_name
                FROM blog_posts JOIN users ON users.id = blog_posts.author_id
                WHERE blog_posts.id = ?
                """,
                (post_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Unable to read newly created blog post")
        return {
            "id": row["id"],
            "title": row["title"],
            "excerpt": row["excerpt"],
            "content": row["content"],
            "author": row["author_name"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "isMine": True,
        }
    finally:
        connection.close()


def _update_blog_post(
    config: Settings, post_id: int, author_id: int, post: BlogPostRequest
) -> dict[str, Any] | None:
    connection = _connect_auth_database(config)
    try:
        with connection:
            cursor = connection.execute(
                """
                UPDATE blog_posts
                SET title = ?, excerpt = ?, content = ?, updated_at = ?
                WHERE id = ? AND author_id = ?
                """,
                (
                    post.title,
                    post.excerpt,
                    post.content,
                    datetime.now(timezone.utc).isoformat(),
                    post_id,
                    author_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                """
                SELECT blog_posts.id, blog_posts.title, blog_posts.excerpt,
                       blog_posts.content, blog_posts.created_at,
                       blog_posts.updated_at, users.display_name AS author_name
                FROM blog_posts JOIN users ON users.id = blog_posts.author_id
                WHERE blog_posts.id = ?
                """,
                (post_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "excerpt": row["excerpt"],
            "content": row["content"],
            "author": row["author_name"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "isMine": True,
        }
    finally:
        connection.close()


def _delete_blog_post(config: Settings, post_id: int, author_id: int) -> bool:
    connection = _connect_auth_database(config)
    try:
        with connection:
            cursor = connection.execute(
                "DELETE FROM blog_posts WHERE id = ? AND author_id = ?",
                (post_id, author_id),
            )
            return cursor.rowcount > 0
    finally:
        connection.close()


def create_app(config: Settings = settings) -> SecurityHeadersMiddleware:
    @asynccontextmanager
    async def lifespan(_api: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(_initialize_auth_database, config)
        yield

    api = FastAPI(
        title="Portfolio API",
        lifespan=lifespan,
        docs_url="/docs" if config.is_development else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.is_development else None,
    )
    rate_limiter = ContactRateLimiter(
        config.contact_rate_limit, config.contact_rate_window_seconds
    )
    auth_rate_limiter = ContactRateLimiter(
        config.auth_rate_limit, config.auth_rate_window_seconds
    )
    session_cookie_name = (
        "__Host-blog_session" if config.app_env == "production" else "blog_session"
    )

    api.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
        max_age=600,
    )
    api.add_middleware(RequestSizeLimitMiddleware, max_bytes=config.max_request_size)
    api.add_middleware(
        ContactRequestGuardMiddleware,
        limiter=rate_limiter,
        allowed_origins=config.allowed_origins,
    )
    api.add_middleware(
        AuthRequestGuardMiddleware,
        limiter=auth_rate_limiter,
        allowed_origins=config.allowed_origins,
    )
    if config.force_https:
        api.add_middleware(HTTPSRedirectMiddleware)
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)

    @api.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "loc": error.get("loc", ()),
                "msg": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/api/contact", status_code=202)
    async def submit_contact(
        submission: ContactSubmission, request: Request
    ) -> dict[str, str]:
        try:
            await asyncio.to_thread(_store_submission, config, submission)
        except OSError:
            logger.exception("Unable to persist contact submission")
            raise HTTPException(
                status_code=503, detail="Contact submissions are temporarily unavailable"
            ) from None

        return {"status": "received"}

    def set_session_cookie(response: JSONResponse, token: str) -> None:
        response.set_cookie(
            key=session_cookie_name,
            value=token,
            max_age=7 * 24 * 60 * 60,
            httponly=True,
            secure=config.app_env == "production",
            samesite="lax",
            path="/",
        )

    @api.post("/api/auth/signup", status_code=201)
    async def sign_up(payload: SignUpRequest) -> JSONResponse:
        try:
            result = await asyncio.to_thread(
                _register_user,
                config,
                payload.email,
                payload.password,
                payload.display_name,
            )
        except (OSError, sqlite3.Error):
            logger.exception("Unable to persist blog account")
            raise HTTPException(
                status_code=503, detail="Account service is temporarily unavailable"
            ) from None
        if result is None:
            raise HTTPException(status_code=409, detail="An account already exists")
        user, token = result
        response = JSONResponse(status_code=201, content={"user": user})
        set_session_cookie(response, token)
        return response

    @api.post("/api/auth/login")
    async def log_in(payload: LoginRequest) -> JSONResponse:
        try:
            result = await asyncio.to_thread(
                _login_user, config, payload.email, payload.password
            )
        except (OSError, sqlite3.Error):
            logger.exception("Unable to access blog account storage")
            raise HTTPException(
                status_code=503, detail="Account service is temporarily unavailable"
            ) from None
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        user, token = result
        response = JSONResponse(content={"user": user})
        set_session_cookie(response, token)
        return response

    @api.get("/api/auth/me")
    async def current_user(request: Request) -> dict[str, Any]:
        try:
            user = await asyncio.to_thread(
                _resolve_session, config, request.cookies.get(session_cookie_name)
            )
        except (OSError, sqlite3.Error):
            logger.exception("Unable to resolve blog session")
            raise HTTPException(
                status_code=503, detail="Account service is temporarily unavailable"
            ) from None
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user": user}

    async def require_blog_user(request: Request) -> dict[str, Any]:
        try:
            user = await asyncio.to_thread(
                _resolve_session, config, request.cookies.get(session_cookie_name)
            )
        except (OSError, sqlite3.Error):
            logger.exception("Unable to resolve blog author session")
            raise HTTPException(
                status_code=503, detail="Account service is temporarily unavailable"
            ) from None
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in to manage blog posts")
        return user

    @api.get("/api/posts")
    async def list_posts(request: Request) -> dict[str, Any]:
        try:
            user = await asyncio.to_thread(
                _resolve_session, config, request.cookies.get(session_cookie_name)
            )
            posts = await asyncio.to_thread(
                _list_blog_posts, config, user["id"] if user else None
            )
        except (OSError, sqlite3.Error):
            logger.exception("Unable to list blog posts")
            raise HTTPException(
                status_code=503, detail="Blog posts are temporarily unavailable"
            ) from None
        return {"posts": posts}

    @api.post("/api/posts", status_code=201)
    async def create_post(
        payload: BlogPostRequest, request: Request
    ) -> dict[str, Any]:
        user = await require_blog_user(request)
        try:
            post = await asyncio.to_thread(
                _create_blog_post, config, user["id"], payload
            )
        except (OSError, sqlite3.Error):
            logger.exception("Unable to create blog post")
            raise HTTPException(
                status_code=503, detail="Blog posts are temporarily unavailable"
            ) from None
        return {"post": post}

    @api.put("/api/posts/{post_id}")
    async def update_post(
        post_id: int, payload: BlogPostRequest, request: Request
    ) -> dict[str, Any]:
        if post_id < 1:
            raise HTTPException(status_code=404, detail="Blog post not found")
        user = await require_blog_user(request)
        try:
            post = await asyncio.to_thread(
                _update_blog_post, config, post_id, user["id"], payload
            )
        except (OSError, sqlite3.Error):
            logger.exception("Unable to update blog post")
            raise HTTPException(
                status_code=503, detail="Blog posts are temporarily unavailable"
            ) from None
        if post is None:
            raise HTTPException(status_code=404, detail="Blog post not found")
        return {"post": post}

    @api.delete("/api/posts/{post_id}")
    async def delete_post(post_id: int, request: Request) -> dict[str, str]:
        if post_id < 1:
            raise HTTPException(status_code=404, detail="Blog post not found")
        user = await require_blog_user(request)
        try:
            deleted = await asyncio.to_thread(
                _delete_blog_post, config, post_id, user["id"]
            )
        except (OSError, sqlite3.Error):
            logger.exception("Unable to delete blog post")
            raise HTTPException(
                status_code=503, detail="Blog posts are temporarily unavailable"
            ) from None
        if not deleted:
            raise HTTPException(status_code=404, detail="Blog post not found")
        return {"status": "deleted"}

    @api.post("/api/auth/logout")
    async def log_out(request: Request) -> JSONResponse:
        token = request.cookies.get(session_cookie_name)
        try:
            await asyncio.to_thread(_revoke_session, config, token)
        except (OSError, sqlite3.Error):
            logger.exception("Unable to revoke blog session")
            raise HTTPException(
                status_code=503, detail="Account service is temporarily unavailable"
            ) from None
        response = JSONResponse(content={"status": "logged_out"})
        response.delete_cookie(
            key=session_cookie_name,
            httponly=True,
            secure=config.app_env == "production",
            samesite="lax",
            path="/",
        )
        return response

    return SecurityHeadersMiddleware(api)


app = create_app()
