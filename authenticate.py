#!/usr/bin/env python3
"""
Initial authentication script for Trakt.tv
Run this once to create the trakt.json token file
"""
import os
import json
from dotenv import load_dotenv
from trakt import Trakt

load_dotenv()

TOKEN_FILE = 'trakt.json'
CLIENT_ID = os.getenv('TRAKT_CLIENT_ID')
CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET')

def authenticate():
    """Perform initial OAuth authentication with Trakt"""
    
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: TRAKT_CLIENT_ID and TRAKT_CLIENT_SECRET must be set in .env file")
        return False
    
    if os.path.exists(TOKEN_FILE):
        print(f"✓ {TOKEN_FILE} already exists. Delete it first if you want to re-authenticate.")
        return True
    
    print("Trakt Authentication")
    print("=" * 50)
    
    # Configure Trakt client
    Trakt.configuration.defaults.client(
        id=CLIENT_ID,
        secret=CLIENT_SECRET
    )
    
    # Start device authentication flow
    print("\nStarting authentication flow...")
    try:
        code = Trakt['oauth/device'].code()
    except Exception as e:
        print(f"✗ Failed to get device code: {e}")
        return False
    
    print(f"\n1. Visit this URL in your browser:\n   {code.get('verification_url')}")
    print(f"\n2. Enter this code: {code.get('user_code')}")
    print(f"\n3. Waiting for authorization (expires in {code.get('expires_in')} seconds)...")
    print("   Press Ctrl+C to cancel\n")
    
    # Poll for authorization
    try:
        token = Trakt['oauth/device'].poll(**code)
    except Exception as e:
        print(f"\n✗ Polling failed: {e}")
        return False
    
    if not token:
        print("\n✗ Authentication timed out or was denied")
        return False
    
    # Save token to file
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token, f, indent=2)
    
    print(f"\n✓ Authentication successful! Token saved to {TOKEN_FILE}")
    print("  You can now run the app with: python app.py")
    return True

if __name__ == "__main__":
    authenticate()
