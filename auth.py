"""
Yahoo Fantasy Sports OAuth 2.0 authentication.

First run: call run_oauth_flow() or run as a script (python auth.py).
All subsequent runs: call get_access_token() to silently refresh.
"""

import base64
import os
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

YAHOO_AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

_ENV_FILE = Path(__file__).parent / ".env"


def _load_env() -> None:
    load_dotenv(_ENV_FILE, override=True)


def _basic_auth_header() -> dict:
    client_id = os.getenv("YAHOO_CLIENT_ID", "")
    client_secret = os.getenv("YAHOO_CLIENT_SECRET", "")
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def get_auth_url() -> str:
    _load_env()
    client_id = os.getenv("YAHOO_CLIENT_ID", "")
    return (
        f"{YAHOO_AUTH_URL}"
        f"?client_id={client_id}"
        "&redirect_uri=oob"
        "&response_type=code"
    )


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


def exchange_code(code: str) -> str:
    """
    Exchange a Yahoo authorization code for access + refresh tokens.
    Saves the refresh token to InstantDB and .env, then returns the access token.
    """
    _load_env()
    headers = _basic_auth_header()
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": "oob",
        "code": code,
    }
    resp = requests.post(YAHOO_TOKEN_URL, headers=headers, data=data, timeout=30)
    resp.raise_for_status()
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
        "redirect_uri": "oob",
        "refresh_token": refresh_token,
    }
    resp = requests.post(YAHOO_TOKEN_URL, headers=headers, data=data, timeout=30)
    resp.raise_for_status()
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
    url = get_auth_url()
    print("\nOpening Yahoo authorization page in your browser...")
    webbrowser.open(url)
    print(f"\nIf the browser didn't open, visit:\n{url}")
    code = input("\nPaste the verification code shown by Yahoo: ").strip()
    try:
        exchange_code(code)
        print("\n✓ Success! Your refresh token has been saved to .env")
        print("  You can now run: streamlit run app.py")
    except Exception as exc:
        print(f"\n✗ Authorization failed: {exc}")
