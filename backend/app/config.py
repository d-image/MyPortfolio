from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def _split_csv(value: str | None, fallback: list[str]) -> list[str]:
    if value is None:
        return fallback.copy()
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("APP_FORCE_HTTPS must be a boolean value")


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    host: str = field(default_factory=lambda: os.getenv("APP_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _as_int("APP_PORT", 8000))
    allowed_origins: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("APP_ALLOWED_ORIGINS"),
            ["http://localhost:5173", "http://127.0.0.1:5173"],
        )
    )
    allowed_hosts: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("APP_ALLOWED_HOSTS"), ["localhost", "127.0.0.1"]
        )
    )
    force_https: bool = field(
        default_factory=lambda: _as_bool(os.getenv("APP_FORCE_HTTPS"), default=False)
    )
    max_request_size: int = field(
        default_factory=lambda: _as_int("APP_MAX_REQUEST_SIZE", 1_048_576)
    )
    contact_rate_limit: int = field(
        default_factory=lambda: _as_int("APP_CONTACT_RATE_LIMIT", 5)
    )
    contact_rate_window_seconds: int = field(
        default_factory=lambda: _as_int("APP_CONTACT_RATE_WINDOW_SECONDS", 300)
    )
    auth_rate_limit: int = field(
        default_factory=lambda: _as_int("APP_AUTH_RATE_LIMIT", 10)
    )
    auth_rate_window_seconds: int = field(
        default_factory=lambda: _as_int("APP_AUTH_RATE_WINDOW_SECONDS", 900)
    )
    submissions_file: str = field(
        default_factory=lambda: os.getenv(
            "APP_SUBMISSIONS_FILE", "backend/runtime/contact_submissions.jsonl"
        )
    )
    auth_database_file: str = field(
        default_factory=lambda: os.getenv(
            "APP_AUTH_DATABASE_FILE", "backend/runtime/blog_auth.sqlite3"
        )
    )

    def __post_init__(self) -> None:
        normalized_env = self.app_env.strip().lower()
        if normalized_env not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development, test, or production")
        object.__setattr__(self, "app_env", normalized_env)

        if not 1 <= self.port <= 65535:
            raise ValueError("APP_PORT must be between 1 and 65535")
        if not 1 <= self.max_request_size <= 10 * 1024 * 1024:
            raise ValueError("APP_MAX_REQUEST_SIZE must be between 1 byte and 10 MiB")
        if self.contact_rate_limit < 1:
            raise ValueError("APP_CONTACT_RATE_LIMIT must be positive")
        if self.contact_rate_window_seconds < 1:
            raise ValueError("APP_CONTACT_RATE_WINDOW_SECONDS must be positive")
        if self.auth_rate_limit < 1:
            raise ValueError("APP_AUTH_RATE_LIMIT must be positive")
        if self.auth_rate_window_seconds < 1:
            raise ValueError("APP_AUTH_RATE_WINDOW_SECONDS must be positive")
        if not self.submissions_file.strip():
            raise ValueError("APP_SUBMISSIONS_FILE must not be empty")
        if not self.auth_database_file.strip():
            raise ValueError("APP_AUTH_DATABASE_FILE must not be empty")
        if not self.allowed_hosts or any(
            not host or "/" in host or any(char.isspace() for char in host)
            for host in self.allowed_hosts
        ):
            raise ValueError("APP_ALLOWED_HOSTS must contain valid host names")
        if self.app_env == "production" and "*" in self.allowed_hosts:
            raise ValueError("Wildcard hosts are not allowed in production")

        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError(
                    "APP_ALLOWED_ORIGINS must contain exact HTTP or HTTPS origins"
                )
            if self.app_env == "production" and parsed.scheme != "https":
                raise ValueError("Production APP_ALLOWED_ORIGINS must use HTTPS")

        if self.app_env == "production" and (
            not self.allowed_origins or not self.allowed_hosts
        ):
            raise ValueError("Production requires explicit allowed origins and hosts")
        if self.app_env == "production" and any(
            host.lower() in {"localhost", "127.0.0.1", "::1"}
            for host in self.allowed_hosts
        ):
            raise ValueError("Production APP_ALLOWED_HOSTS must not use local hosts")

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


settings = Settings()
