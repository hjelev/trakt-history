#!/usr/bin/env python3
"""
Minimal Trakt API wrapper for authentication and basic access.
This file is imported by update_trakt_local.py script.
Uses single authentication to fetch watch history for multiple users.
"""
import os
import json
from dotenv import load_dotenv
from trakt import Trakt

load_dotenv()

# Configuration
TOKEN_FILE = 'trakt.json'
CLIENT_ID = os.getenv('TRAKT_CLIENT_ID')
CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET')


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
