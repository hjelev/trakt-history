#!/usr/bin/env python3
"""
Cast lookups via TMDB's free API, keyed by the tmdb id Trakt's scraped
history payload already supplies (no title search/matching needed).

Genres, posters/fanart, and all external ids come straight from the
scraped Trakt payload (trakt_scraper.py) -- this module exists only to
fill the one gap: cast, which Trakt's history endpoint doesn't include.
"""
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

TMDB_API_KEY = os.getenv('TMDB_API_KEY')
TMDB_BASE = 'https://api.themoviedb.org/3'

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_data', 'tmdb_cache.json')

_cache = None


def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r') as f:
                _cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            _cache = {}
    else:
        _cache = {}
    return _cache


def save_cache() -> None:
    if _cache is None:
        return
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w') as f:
        json.dump(_cache, f, indent=2)


def get_cast(tmdb_id, media_type: str, limit: int = 5) -> list:
    """Return up to `limit` top-billed cast names for a movie/show tmdb id.

    media_type must be 'movie' or 'show' (episodes use their parent show's
    tmdb id). Returns [] if TMDB_API_KEY is unset, the id is missing, or
    the lookup fails -- callers should treat missing cast as non-fatal,
    same as the old Trakt-based cast fetch did.
    """
    if not tmdb_id or not TMDB_API_KEY:
        return []

    tmdb_media_type = 'tv' if media_type == 'show' else 'movie'
    cache_key = f'{tmdb_media_type}:{tmdb_id}'
    cache = _load_cache()
    if cache_key in cache:
        return cache[cache_key]

    try:
        response = requests.get(
            f'{TMDB_BASE}/{tmdb_media_type}/{tmdb_id}/credits',
            params={'api_key': TMDB_API_KEY},
            timeout=10,
        )
        if response.status_code != 200:
            cache[cache_key] = []
            return []
        data = response.json()
        cast_list = data.get('cast', [])
        names = [c.get('name') for c in cast_list[:limit] if c.get('name')]
        cache[cache_key] = names
        return names
    except (requests.RequestException, ValueError):
        cache[cache_key] = []
        return []
