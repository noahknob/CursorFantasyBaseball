"""
Yahoo Fantasy Sports OAuth 2.0 authentication.

First run: call run_oauth_flow() or run as a script (python auth.py).
All subsequent runs: call get_access_token() to silently refresh.
"""

from __future__ import annotations

import base64
import os
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

YAHOO_AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

# Registered redirect URI in Yahoo Developer console.
# Must exactly match what is configured at
# https://developer.yahoo.com/apps/ → your app → Redirect URI(s).
DEFAULT_YAHOO_REDIRECT_URI = "https://weeklyroto1.streamlit.app"
OOB_REDIRECT_URI = "oob"

_ENV_FILE = Path(__file__).parent / ".env"


def _load_env() -> None:
    load_dotenv(_ENV_FILE, override=True)


def _redirect_uri() -> str:
    _load_env()
    return os.getenv("YAHOO_REDIRECT_URI", DEFAULT_YAHOO_REDIRECT_URI).strip()


def get_oauth_config_errors() -> list[str]:
    _load_env()
    errors: list[str] = []
    if not os.getenv("YAHOO_CLIENT_ID", "").strip():
        errors.append("YAHOO_CLIENT_ID is missing")
    if not os.getenv("YAHOO_CLIENT_SECRET", "").strip():
        errors.append("YAHOO_CLIENT_SECRET is missing")
    if not _redirect_uri():
        errors.append("YAHOO_REDIRECT_URI is missing")
    return errors


def _basic_auth_header() -> dict:
    client_id = os.getenv("YAHOO_CLIENT_ID", "")
    client_secret = os.getenv("YAHOO_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise ValueError(
            "Yahoo OAuth is not configured. Add YAHOO_CLIENT_ID and "
            "YAHOO_CLIENT_SECRET before authorizing."
        )
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def get_auth_url(redirect_uri: str | None = None) -> str:
    _load_env()
    client_id = os.getenv("YAHOO_CLIENT_ID", "")
    redirect_uri = (redirect_uri or _redirect_uri()).strip()
    if not client_id:
        raise ValueError(
            "Yahoo OAuth is not configured. Add YAHOO_CLIENT_ID before authorizing."
        )
    if not redirect_uri:
        raise ValueError(
            "Yahoo OAuth is not configured. Add YAHOO_REDIRECT_URI before authorizing."
        )
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "fspt-r",
        "language": "en-us",
    })
    return f"{YAHOO_AUTH_URL}?{params}"


def _raise_yahoo_token_error(resp: requests.Response, *, redirect_uri: str) -> None:
    """Raise a readable error that includes Yahoo's response details."""
    try:
        payload = resp.json()
    except Exception:
        payload = {}

    error = str(payload.get("error", "")).strip()
    description = str(payload.get("error_description", "")).strip()
    text = resp.text.strip()

    details = []
    if error:
        details.append(error)
    if description:
        details.append(description)
    elif text and text not in details:
        details.append(text)

    message = "Yahoo token exchange failed"
    if details:
        message = f"{message}: {' | '.join(details)}"

    if error == "invalid_client":
        message += (
            " | Verify the Yahoo client ID and client secret in Streamlit secrets "
            "match the Yahoo Developer app exactly."
        )
    elif error == "invalid_grant":
        message += (
            " | The authorization code may have expired, already been used, or "
            "been issued for a different redirect URI."
        )
    elif error == "invalid_request":
        message += (
            " | Verify the redirect URI in Streamlit secrets matches the Yahoo "
            "Developer app exactly."
        )

    message += f" | redirect_uri={redirect_uri}"
    raise RuntimeError(message)


def _save_refresh_token(token: str) -> None:
    """Persist token to InstantDB (cloud) and .env (local). Fails silently."""
    try:
        import instant_db as _idb
        _idb.save_refresh_token(token)
    except Exception:
        pass
    try:
        set_key(str(_ENV_FILE), "YAHOO_REFRESH_TOKEN", token)
        _load_env()
    except Exception:
        pass


def _load_refresh_token() -> str:
    """Return the most up-to-date refresh token: InstantDB first, then env."""
    try:
        import instant_db as _idb
        token = _idb.load_refresh_token()
        if token:
            return token
    except Exception:
        pass
    return os.getenv("YAHOO_REFRESH_TOKEN", "").strip()


def exchange_code(code: str, redirect_uri: str | None = None) -> str:
    """
    Exchange a Yahoo authorization code for access + refresh tokens.
    Saves the refresh token to InstantDB and .env, then returns the access token.
    """
    redirect_uri = (redirect_uri or _redirect_uri()).strip()
    _load_env()
    headers = _basic_auth_header()
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }
    resp = requests.post(YAHOO_TOKEN_URL, headers=headers, data=data, timeout=30)
    if not resp.ok:
        _raise_yahoo_token_error(resp, redirect_uri=data["redirect_uri"])
    tokens = resp.json()

    _save_refresh_token(tokens["refresh_token"])
    return tokens["access_token"]


def get_access_token() -> str:
    """
    Load the saved refresh token and exchange it for a fresh access token.
    Prefers the InstantDB-stored token (survives cloud restarts) over .env.
    Rotates the token in both InstantDB and .env if Yahoo issues a new one.
    Raises ValueError if no refresh token has been saved yet.
    """
    _load_env()
    refresh_token = _load_refresh_token()
    if not refresh_token:
        raise ValueError(
            "No Yahoo refresh token found. Complete the one-time OAuth setup first."
        )

    headers = _basic_auth_header()
    data = {
        "grant_type": "refresh_token",
        "redirect_uri": OOB_REDIRECT_URI,
        "refresh_token": refresh_token,
    }
    resp = requests.post(YAHOO_TOKEN_URL, headers=headers, data=data, timeout=30)
    if not resp.ok:
        _raise_yahoo_token_error(resp, redirect_uri=data["redirect_uri"])
    tokens = resp.json()

    new_refresh = tokens.get("refresh_token", "").strip()
    if new_refresh and new_refresh != refresh_token:
        _save_refresh_token(new_refresh)

    return tokens["access_token"]


def has_refresh_token() -> bool:
    _load_env()
    return bool(_load_refresh_token())


# ─── CLI one-time setup ───────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Yahoo Fantasy Sports — One-Time OAuth Setup")
    print("=" * 45)
    print(
        "\nNOTE: This CLI flow is for local use only."
        f"\n      The redirect URI is set to: {_redirect_uri()}"
        "\n      After authorizing, Yahoo will redirect to that URL."
        "\n      Copy the 'code' query-parameter value from the redirected URL."
    )
    url = get_auth_url()
    print("\nOpening Yahoo authorization page in your browser...")
    webbrowser.open(url)
    print(f"\nIf the browser didn't open, visit:\n{url}")
    code = input(
        "\nPaste the 'code' value from the redirect URL: "
    ).strip()
    try:
        exchange_code(code)
        print("\n✓ Success! Your refresh token has been saved to .env")
        print("  You can now run: streamlit run app.py")
    except Exception as exc:
        print(f"\n✗ Authorization failed: {exc}")
