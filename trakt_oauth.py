#!/usr/bin/env python3
"""
Per-user Trakt OAuth (authorization-code flow with PKCE) for the web login.

Tokens live in _data/tokens/<username>.json, so each configured user can log
in with their own Trakt account and rate items from the site.

Trakt apps created since October 2026 have no client secret, so this is PKCE
only and never sends one. Access tokens last 7 days and refresh tokens are
single-use; the web app and the scheduler share the token files, so refreshing
is done under a file lock.
"""
import base64
import fcntl
import hashlib
import json
import os
import secrets
import time
from contextlib import contextmanager
from urllib.parse import quote, urlencode

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

CLIENT_ID = os.getenv('TRAKT_CLIENT_ID')
REDIRECT_URI = os.getenv('TRAKT_REDIRECT_URI')

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '_data'))
TOKENS_DIR = os.path.join(DATA_DIR, 'tokens')

AUTHORIZE_URL = 'https://auth.trakt.tv/oauth/authorize'
TOKEN_URL = 'https://auth.trakt.tv/oauth/token'
API_BASE = 'https://api.trakt.tv'
USER_AGENT = 'trakt-history/1.0'


def is_configured() -> bool:
    return bool(CLIENT_ID and REDIRECT_URI)


def token_path(username: str) -> str:
    return os.path.join(TOKENS_DIR, f"{quote(username, safe='')}.json")


def load_token(username: str):
    path = token_path(username)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_token(username: str, token_data: dict) -> None:
    os.makedirs(TOKENS_DIR, mode=0o700, exist_ok=True)
    path = token_path(username)
    tmp = f'{path}.{secrets.token_hex(4)}.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(token_data, f, indent=2)
    os.replace(tmp, path)


@contextmanager
def _token_lock(username: str):
    """Serialize refreshes of one user's token across processes."""
    os.makedirs(TOKENS_DIR, mode=0o700, exist_ok=True)
    with open(token_path(username) + '.lock', 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def build_authorize_url(state: str, code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    return AUTHORIZE_URL + '?' + urlencode({
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    })


def _post_token(body: dict, what: str):
    """POST to the token endpoint. Returns the token dict, or None on failure."""
    try:
        response = requests.post(
            TOKEN_URL,
            json={'client_id': CLIENT_ID, 'redirect_uri': REDIRECT_URI, **body},
            headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT},
            timeout=30,
        )
        if response.status_code != 200:
            print(f"Error: {what} failed ({response.status_code}): {response.text[:300]}")
            return None
        token_data = response.json()
    except (requests.RequestException, ValueError) as e:
        print(f"Error: {what} failed: {e}")
        return None
    if not isinstance(token_data, dict) or not token_data.get('access_token'):
        print(f"Error: {what} returned no access token")
        return None
    token_data.setdefault('created_at', int(time.time()))
    return token_data


def exchange_code_for_token(code: str, code_verifier: str):
    """Exchange an OAuth authorization code for an access/refresh token pair."""
    return _post_token({
        'code': code,
        'code_verifier': code_verifier,
        'grant_type': 'authorization_code',
    }, 'code exchange')


def token_expired(token_data: dict, skew_seconds: int = 60) -> bool:
    """Return True if the token is expired (with a small safety skew)."""
    if not isinstance(token_data, dict):
        return True

    created_at = token_data.get('created_at')
    expires_in = token_data.get('expires_in')
    if created_at is None or expires_in is None:
        return True

    try:
        return time.time() >= (float(created_at) + float(expires_in) - skew_seconds)
    except (TypeError, ValueError):
        return True


def refresh_token(username: str, token_data: dict):
    """Refresh an expired access token using its stored refresh token."""
    refresh_tok = token_data.get('refresh_token')
    if not refresh_tok:
        print(f"Error: refresh_token missing for {username}; re-login required.")
        return None
    refreshed = _post_token({
        'refresh_token': refresh_tok,
        'grant_type': 'refresh_token',
    }, f'token refresh for {username}')
    if refreshed:
        save_token(username, refreshed)
    return refreshed


def get_valid_access_token(username: str):
    """Load this user's token, refreshing it first if expired. None if unavailable."""
    token_data = load_token(username)
    if not token_data:
        return None
    if token_expired(token_data):
        with _token_lock(username):
            # Another process may have refreshed it while we waited
            token_data = load_token(username)
            if token_data and token_expired(token_data):
                token_data = refresh_token(username, token_data)
        if not token_data:
            return None
    return token_data.get('access_token')


def build_headers(access_token: str = None) -> dict:
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': USER_AGENT,
        'trakt-api-version': '2',
        'trakt-api-key': CLIENT_ID or '',
    }
    if access_token:
        headers['Authorization'] = f'Bearer {access_token}'
    return headers


def fetch_authenticated_usernames(access_token: str) -> list:
    """Names (slug, username) of the account behind this token; [] on failure."""
    try:
        response = requests.get(
            f'{API_BASE}/users/me',
            headers=build_headers(access_token),
            timeout=30,
        )
        if response.status_code != 200:
            print(f"Error: /users/me failed ({response.status_code}): {response.text[:300]}")
            return []
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        print(f"Error: /users/me failed: {e}")
        return []
    names = [(data.get('ids') or {}).get('slug'), data.get('username')]
    return [n for n in names if n]
