"""Shared configuration loaded from the project-root .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value.strip() if value else default


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else PROJECT_ROOT / p


@dataclass(frozen=True)
class YouTubeSettings:
    api_key: str = field(default_factory=lambda: _env("YOUTUBE_API_KEY"))
    channel_id: str = field(default_factory=lambda: _env("YOUTUBE_CHANNEL_ID"))
    channel_handle: str = field(default_factory=lambda: _env("YOUTUBE_CHANNEL_HANDLE"))
    client_id: str = field(default_factory=lambda: _env("YOUTUBE_CLIENT_ID"))
    client_secret: str = field(default_factory=lambda: _env("YOUTUBE_CLIENT_SECRET"))
    token_file: Path = field(
        default_factory=lambda: _resolve(_env("YOUTUBE_TOKEN_FILE", ".secrets/youtube_token.json"))
    )

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def has_oauth_client(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def has_token(self) -> bool:
        return self.token_file.exists()

    @property
    def default_channel(self) -> str:
        """Channel ID or @handle to use when none is passed on the CLI."""
        return self.channel_id or self.channel_handle


@dataclass(frozen=True)
class AirtableSettings:
    api_key: str = field(default_factory=lambda: _env("AIRTABLE_API_KEY"))
    base_id: str = field(default_factory=lambda: _env("AIRTABLE_BASE_ID"))


@dataclass(frozen=True)
class MetricoolSettings:
    user_token: str = field(default_factory=lambda: _env("METRICOOL_USER_TOKEN"))
    user_id: str = field(default_factory=lambda: _env("METRICOOL_USER_ID"))
    blog_id: str = field(default_factory=lambda: _env("METRICOOL_BLOG_ID"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: _resolve(_env("DATA_DIR", "data")))
    youtube: YouTubeSettings = field(default_factory=YouTubeSettings)
    airtable: AirtableSettings = field(default_factory=AirtableSettings)
    metricool: MetricoolSettings = field(default_factory=MetricoolSettings)


settings = Settings()
