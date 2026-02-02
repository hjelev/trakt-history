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
    Authenticate with Trakt using stored token.
    Returns True if authentication successful, False otherwise.
    """
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: TRAKT_CLIENT_ID and TRAKT_CLIENT_SECRET must be set in .env")
        return False
    
    Trakt.configuration.defaults.client(id=CLIENT_ID, secret=CLIENT_SECRET)
    
    if not os.path.exists(TOKEN_FILE):
        print(f"Error: Token file {TOKEN_FILE} not found. Run authenticate.py first.")
        return False
    
    try:
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)
        
        if not token_data:
            print(f"Error: Token file {TOKEN_FILE} is empty")
            return False

        if _token_expired(token_data):
            print("Token expired; attempting refresh...")
            refreshed = _refresh_token(token_data)
            if not refreshed:
                return False
            token_data = refreshed
            
        Trakt.configuration.defaults.oauth.from_response(token_data)
        return True
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {TOKEN_FILE}: {e}")
        return False
    except Exception as e:
        print(f"Error loading token: {e}")
        return False


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
