#!/usr/bin/env python3
"""
Minimal Trakt API wrapper for authentication and basic access.
This file is imported by update_trakt_local.py script.
Uses single authentication to fetch watch history for multiple users.
"""
import os
import json
import time
import requests
from dotenv import load_dotenv
from trakt import Trakt

load_dotenv()

# Configuration
TOKEN_FILE = 'trakt.json'
CLIENT_ID = os.getenv('TRAKT_CLIENT_ID')
CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET')

# Export Trakt and CLIENT_ID for use by update_trakt_local.py
__all__ = ['Trakt', 'CLIENT_ID', 'authenticate']


def _token_expired(token_data, skew_seconds=60):
    """Return True if token is expired (with a small safety skew)."""
    if not isinstance(token_data, dict):
        return True

    expires_at = token_data.get('expires_at')
    if expires_at is not None:
        try:
            return time.time() >= float(expires_at) - skew_seconds
        except (TypeError, ValueError):
            return True

    created_at = token_data.get('created_at')
    expires_in = token_data.get('expires_in')
    if created_at is None or expires_in is None:
        # Missing data; assume not expired to avoid unnecessary failures
        return False

    try:
        return time.time() >= (float(created_at) + float(expires_in) - skew_seconds)
    except (TypeError, ValueError):
        return True


def _refresh_token(token_data):
    """Refresh access token using the stored refresh token."""
    refresh_token = token_data.get('refresh_token')
    if not refresh_token:
        print("Error: refresh_token missing from trakt.json; re-authentication required.")
        return None

    response = requests.post(
        'https://api.trakt.tv/oauth/token',
        json={
            'refresh_token': refresh_token,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'refresh_token'
        },
        headers={
            'Content-Type': 'application/json'
        },
        timeout=30
    )

    if response.status_code != 200:
        print(f"Error: token refresh failed ({response.status_code}): {response.text}")
        return None

    try:
        refreshed = response.json()
    except Exception as e:
        print(f"Error: unable to parse refresh response: {e}")
        return None

    # Persist refreshed token
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(refreshed, f, indent=2)
    except Exception as e:
        print(f"Error: failed to write refreshed token: {e}")
        return None

    return refreshed


def authenticate():
    """
    Configure the shared Trakt client, best-effort attaching the legacy
    device-flow OAuth token from trakt.json for any callers that still use
    the trakt.py library directly (e.g. public shows/seasons enrichment
    calls, which only need the client id/key, not OAuth).

    trakt.json is no longer the source of truth for any per-user private
    API calls (those use trakt_oauth.py's per-user token store instead), so
    a missing/expired/unrefreshable device-flow token here is non-fatal.
    Returns True as long as CLIENT_ID/CLIENT_SECRET are configured; False
    only if those are missing (a real configuration error).
    """
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: TRAKT_CLIENT_ID and TRAKT_CLIENT_SECRET must be set in .env")
        return False

    Trakt.configuration.defaults.client(id=CLIENT_ID, secret=CLIENT_SECRET)

    if not os.path.exists(TOKEN_FILE):
        print(f"Warning: Token file {TOKEN_FILE} not found; continuing without legacy OAuth token.")
        return True

    try:
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)

        if not token_data:
            print(f"Warning: Token file {TOKEN_FILE} is empty; continuing without legacy OAuth token.")
            return True

        if _token_expired(token_data):
            print("Token expired; attempting refresh...")
            refreshed = _refresh_token(token_data)
            if not refreshed:
                print("Warning: legacy trakt.json token could not be refreshed; continuing without it.")
                return True
            token_data = refreshed

        Trakt.configuration.defaults.oauth.from_response(token_data)
        return True
    except json.JSONDecodeError as e:
        print(f"Warning: Invalid JSON in {TOKEN_FILE}: {e}; continuing without legacy OAuth token.")
        return True
    except Exception as e:
        print(f"Warning: error loading legacy token: {e}; continuing without it.")
        return True


if __name__ == "__main__":
    print("This module provides Trakt authentication for other scripts.")
    print("Use authenticate.py to create the initial token.")
    if authenticate():
        print("Authentication successful!")
        
        # Debug: Show what fields are available in history response
        print("\nFetching sample item to show available fields...")
        try:
            history = Trakt['sync/history'].get(pagination=True, per_page=1, extended='full')
            if history:
                item = list(history)[0]
                print(f"\nSample item type: {type(item).__name__}")
                print(f"Available attributes: {dir(item)}")
                item_dict = item.to_dict()
                print(f"\nDictionary keys: {list(item_dict.keys())}")
                print(f"\nSample data:")
                print(json.dumps(item_dict, indent=2, default=str))
        except Exception as e:
            print(f"Error fetching sample: {e}")
    else:
        print("Authentication failed!")
