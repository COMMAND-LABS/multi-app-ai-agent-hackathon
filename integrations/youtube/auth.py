"""OAuth 2.0 helper for private YouTube data (own channel, Analytics reports)."""

from __future__ import annotations

import json
from pathlib import Path

from integrations.config import settings

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _client_config() -> dict:
    yt = settings.youtube
    if not yt.has_oauth_client:
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env for OAuth."
        )
    return {
        "installed": {
            "client_id": yt.client_id,
            "client_secret": yt.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def run_auth_flow(token_file: Path | None = None) -> Path:
    """Open a browser, complete consent, and cache the token. Returns token path."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_file = token_file or settings.youtube.token_file
    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    return token_file


def load_credentials(token_file: Path | None = None):
    """Load cached OAuth credentials, refreshing if expired. Returns None if absent."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_file = token_file or settings.youtube.token_file
    if not token_file.exists():
        return None
    creds = Credentials.from_authorized_user_info(json.loads(token_file.read_text()), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
    return creds


def access_token() -> str | None:
    creds = load_credentials()
    return creds.token if creds and creds.valid else None
