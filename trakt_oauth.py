#!/usr/bin/env python3
"""
Per-user Trakt OAuth (authorization-code flow) for the web login feature.

Generalizes the single-admin device-flow token handling in main.py
(_token_expired/_refresh_token) into per-user token storage under
_data/tokens/<username>.json, so multiple configured users can each log in
with their own Trakt account and rate items from the site.
"""
import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv('TRAKT_CLIENT_ID')
CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET')
REDIRECT_URI = os.getenv('TRAKT_REDIRECT_URI')

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '_data'))
TOKENS_DIR = os.path.join(DATA_DIR, 'tokens')

AUTHORIZE_URL = 'https://trakt.tv/oauth/authorize'
TOKEN_URL = 'https://api.trakt.tv/oauth/token'
API_BASE = 'https://api.trakt.tv'


def token_path(username: str) -> str:
    return os.path.join(TOKENS_DIR, f'{username}.json')


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
    os.makedirs(TOKENS_DIR, exist_ok=True)
    with open(token_path(username), 'w') as f:
        json.dump(token_data, f, indent=2)


def build_authorize_url(state: str) -> str:
    return (
        f"{AUTHORIZE_URL}?response_type=code&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&state={state}"
    )


def exchange_code_for_token(code: str):
    """Exchange an OAuth authorization code for an access/refresh token pair."""
    response = requests.post(
        TOKEN_URL,
        json={
            'code': code,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code',
        },
        headers={'Content-Type': 'application/json'},
        timeout=30,
    )
    if response.status_code != 200:
        print(f"Error: code exchange failed ({response.status_code}): {response.text}")
        return None
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Error: unable to parse token response: {e}")
        return None


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

    response = requests.post(
        TOKEN_URL,
        json={
            'refresh_token': refresh_tok,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'refresh_token',
        },
        headers={'Content-Type': 'application/json'},
        timeout=30,
    )
    if response.status_code != 200:
        print(f"Error: token refresh failed for {username} ({response.status_code}): {response.text}")
        return None

    try:
        refreshed = response.json()
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Error: unable to parse refresh response for {username}: {e}")
        return None

    save_token(username, refreshed)
    return refreshed


def get_valid_access_token(username: str):
    """Load this user's token, refreshing it first if expired. None if unavailable."""
    token_data = load_token(username)
    if not token_data:
        return None
    if token_expired(token_data):
        token_data = refresh_token(username, token_data)
        if not token_data:
            return None
    return token_data.get('access_token')


def build_headers(access_token: str) -> dict:
    return {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': CLIENT_ID,
        'Authorization': f'Bearer {access_token}',
    }


def fetch_authenticated_username(access_token: str):
    """Call /users/me with the given token and return the account's Trakt slug."""
    response = requests.get(
        f'{API_BASE}/users/me',
        headers=build_headers(access_token),
        timeout=30,
    )
    if response.status_code != 200:
        print(f"Error: /users/me failed ({response.status_code}): {response.text}")
        return None
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError):
        return None
    return (data.get('ids') or {}).get('slug') or data.get('username')
