#!/usr/bin/env python3
"""
Two-way ratings with Trakt's official API.

sync_user() copies a user's Trakt ratings into their local history file (what
the site displays); push_rating() sends one rating made on the site to Trakt.

Reading needs only TRAKT_CLIENT_ID for users whose profile is public; a user
who has logged in on the site is read with their own token.

Run by hand: python3 trakt_ratings.py [username ...]
"""
import json
import os
import sys
import tempfile
from urllib.parse import quote

import requests

import trakt_oauth

DATA_DIR = trakt_oauth.DATA_DIR
PAGE_SIZE = 250
MAX_PAGES = 200


class RatingError(Exception):
    """A rating Trakt did not accept. status is what the site should answer with."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _data_path(username, kind):
    primary = os.getenv('PRIMARY_USER')
    suffix = '' if username == primary else f'_{username}'
    return os.path.join(DATA_DIR, f'trakt_{kind}{suffix}.json')


def _read_json(path, default):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Replace path atomically, so the site never reads a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _fetch(username, access_token):
    """All ratings as {(type, trakt_id): rating}. Raises requests.RequestException."""
    url = f"{trakt_oauth.API_BASE}/users/{quote(username, safe='')}/ratings"
    ratings = {}
    for page in range(1, MAX_PAGES + 1):
        response = requests.get(
            url,
            headers=trakt_oauth.build_headers(access_token),
            params={'page': page, 'limit': PAGE_SIZE},
            timeout=30,
        )
        response.raise_for_status()
        rows = response.json()
        before = len(ratings)
        for row in rows:
            kind = row.get('type')
            trakt_id = ((row.get(kind) or {}).get('ids') or {}).get('trakt')
            if trakt_id and row.get('rating'):
                ratings[(kind, trakt_id)] = int(row['rating'])
        # Trakt's page-count headers can be placeholders; read until a page
        # brings nothing new
        if not rows or len(ratings) == before:
            return ratings
    raise requests.RequestException(f'more than {MAX_PAGES} pages of ratings')


def fetch_ratings(username):
    """(ratings, authenticated), or (None, False) when Trakt can't be read."""
    if not trakt_oauth.CLIENT_ID:
        print('Warning: Ratings not synced, TRAKT_CLIENT_ID is not set')
        return None, False
    token = trakt_oauth.get_valid_access_token(username)
    for access_token in ([token, None] if token else [None]):
        try:
            return _fetch(username, access_token), bool(access_token)
        except (requests.RequestException, ValueError) as e:
            how = 'with login' if access_token else 'as public profile'
            print(f'Warning: Ratings for {username} not readable {how}: {e}')
    return None, False


def apply_ratings(items, ratings, show_of_episode=None):
    """Set every item's rating from Trakt. An episode without its own rating
    takes its show's. Returns how many items changed."""
    show_of_episode = show_of_episode or {}
    changed = 0
    for item in items:
        trakt_id = (item.get('ids') or {}).get('trakt')
        if not trakt_id:
            continue
        rating = ratings.get((item.get('type'), trakt_id))
        if rating is None and item.get('type') == 'episode':
            rating = ratings.get(('show', show_of_episode.get(trakt_id)))
        if item.get('rating') != rating:
            item['rating'] = rating
            changed += 1
    return changed


def sync_user(username):
    """Refresh the ratings in a user's history file. Returns False when Trakt
    couldn't be read, in which case the existing ratings are left alone."""
    ratings, authenticated = fetch_ratings(username)
    if ratings is None:
        print(f'Ratings: NONE loaded for {username}, keeping existing ratings')
        return False
    path = _data_path(username, 'history')
    data = _read_json(path, None)
    if not data:
        print(f'Ratings: no history file for {username} yet')
        return False
    items = data.get('items', [])
    if not ratings and not authenticated and any(i.get('rating') is not None for i in items):
        # Looks the same as a private profile: don't wipe what we have
        print(f'Ratings: Trakt returned none publicly for {username}, keeping existing ratings')
        return False
    show_of_episode = {}
    for row in _read_json(_data_path(username, 'raw'), []):
        episode_id = ((row.get('episode') or {}).get('ids') or {}).get('trakt')
        show_id = ((row.get('show') or {}).get('ids') or {}).get('trakt')
        if episode_id and show_id:
            show_of_episode[episode_id] = show_id
    changed = apply_ratings(items, ratings, show_of_episode)
    if changed:
        write_json(path, data)
    rated = sum(1 for i in items if i.get('rating') is not None)
    print(f'Ratings: loaded {len(ratings)} from Trakt for {username}, {rated}/{len(items)} items rated, {changed} changed')
    return True


def push_rating(username, item_type, trakt_id, rating):
    """Save one rating to the user's Trakt account. Raises RatingError."""
    access_token = trakt_oauth.get_valid_access_token(username)
    if not access_token:
        raise RatingError('session expired, please log in again', 401)
    key = 'movies' if item_type == 'movie' else 'episodes'
    try:
        response = requests.post(
            f'{trakt_oauth.API_BASE}/sync/ratings',
            json={key: [{'ids': {'trakt': trakt_id}, 'rating': rating}]},
            headers=trakt_oauth.build_headers(access_token),
            timeout=30,
        )
    except requests.RequestException as e:
        print(f'Error: rating by {username} failed: {e}')
        raise RatingError('could not reach Trakt')
    if response.status_code == 401:
        raise RatingError('session expired, please log in again', 401)
    if response.status_code == 429:
        raise RatingError('too many ratings at once, try again in a moment', 429)
    if response.status_code not in (200, 201):
        print(f'Error: rating by {username} rejected ({response.status_code}): {response.text[:300]}')
        raise RatingError(f'Trakt rejected the rating ({response.status_code})')
    try:
        not_found = (response.json().get('not_found') or {}).get(key)
    except (ValueError, AttributeError):
        not_found = None
    if not_found:
        raise RatingError('Trakt does not know this title', 404)


def set_local_rating(username, item_type, trakt_id, rating):
    """Show a rating on the site straight away, without waiting for a sync."""
    path = _data_path(username, 'history')
    data = _read_json(path, None)
    if not data:
        return
    changed = False
    for item in data.get('items', []):
        if item.get('type') == item_type and (item.get('ids') or {}).get('trakt') == trakt_id:
            item['rating'] = rating
            changed = True
    if changed:
        write_json(path, data)


if __name__ == '__main__':
    users = sys.argv[1:]
    if not users:
        extra = os.getenv('ADDITIONAL_USERS', '').split(',')
        users = [u.strip() for u in [os.getenv('PRIMARY_USER', '')] + extra if u.strip()]
    results = [sync_user(u) for u in users]
    sys.exit(0 if all(results) else 1)
