#!/usr/bin/env python3
import os
import json
import importlib.util
import time
from datetime import datetime, timedelta
import urllib.parse
import requests
import argparse
try:
    from dotenv import load_dotenv
except Exception:
    # simple fallback for environments without python-dotenv installed
    def load_dotenv(path=None):
        if not path or not os.path.exists(path):
            return
        with open(path, 'r') as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln or ln.startswith('#'):
                    continue
                if '=' in ln:
                    k, v = ln.split('=', 1)
                    os.environ[k.strip()] = v.strip()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# If this script lives in repo_root/scripts/ then ROOT is repo_root and trakt is under ROOT/trakt
# If this script lives in trakt/scripts/ then ROOT is trakt and MAIN_PY is under ROOT/main.py
if os.path.exists(os.path.join(ROOT, 'main.py')):
    TRAKT_DIR = ROOT
else:
    TRAKT_DIR = os.path.join(ROOT, 'trakt')

RAW_PATH = os.path.join(TRAKT_DIR, '_data', 'trakt_raw.json')
OUT_PATH = os.path.join(TRAKT_DIR, '_data', 'trakt_history.json')
MAIN_PY = os.path.join(TRAKT_DIR, 'main.py')

print(f"update_trakt_local.py: using TRAKT_DIR={TRAKT_DIR}")

def main():
    start_time = datetime.now()
    
    # CLI flags for quicker debug runs
    parser = argparse.ArgumentParser(description='Update local Trakt history and thumbnails')
    parser.add_argument('--limit', type=int, default=0, help='Limit number of history items processed (0 = all)')
    parser.add_argument('--no-images', action='store_true', help='Do not fetch images/thumbnails')
    parser.add_argument('--no-cast', action='store_true', help='Do not fetch cast information (much faster)')
    parser.add_argument('--no-enrichment', action='store_true', help='Do not enrich episodes with show genres/year (much faster)')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('--force', action='store_true', help='Force reprocessing even if raw data unchanged')
    args = parser.parse_args()

    if not os.path.exists(MAIN_PY):
        raise SystemExit('trakt/main.py not found')

    spec = importlib.util.spec_from_file_location('trakt_main_local', MAIN_PY)
    trakt_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trakt_main)

    if not hasattr(trakt_main, 'authenticate'):
        raise SystemExit('trakt/main.py missing authenticate()')

    # authenticate() in main.py expects token file in its working directory; switch cwd temporarily
    prev_cwd = os.getcwd()
    try:
        os.chdir(TRAKT_DIR)
        authed = trakt_main.authenticate()
    finally:
        os.chdir(prev_cwd)

    if not authed:
        raise SystemExit('Authentication failed; ensure trakt/trakt.json exists in the trakt folder')

    # Check for existing cache to enable incremental updates
    start_at = None
    cached_items = []
    if os.path.exists(RAW_PATH) and not args.force:
        try:
            with open(RAW_PATH, 'r') as f:
                cached_items = json.load(f)
            
            # Find the most recent watched_at timestamp
            if cached_items:
                timestamps = []
                for item in cached_items:
                    watched = item.get('watched_at_iso') or item.get('watched_at')
                    if watched:
                        try:
                            if isinstance(watched, str):
                                # Parse ISO format
                                ts = datetime.fromisoformat(watched.replace('Z', '+00:00'))
                            else:
                                ts = watched
                            timestamps.append(ts)
                        except Exception:
                            pass
                
                if timestamps:
                    latest = max(timestamps)
                    # Add 1 second to avoid re-fetching the last item (Trakt's start_at is inclusive)
                    start_at = latest + timedelta(seconds=1)
                    print(f"Found {len(cached_items)} cached items, latest watched: {latest.isoformat()}")
                    print("Fetching only new items since last update (incremental mode)...")
        except Exception as e:
            print(f"Could not read cache for incremental update: {e}")
            cached_items = []
            start_at = None

    if start_at:
        print(f"Fetching new items watched after {start_at.isoformat()}...")
    else:
        print("Fetching full watch history from Trakt API...")
    
    try:
        # Use extended='full' to get all metadata including images
        # Note: Trakt API does not include cast in sync/history endpoint
        # Set a reasonable timeout
        import socket
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(60)  # 60 second timeout for slower connections
        
        print("Calling Trakt API...")
        # Fetch with start_at for incremental updates
        if start_at:
            history_objs = trakt_main.Trakt['sync/history'].get(
                pagination=True, 
                per_page=100, 
                extended='full',
                start_at=start_at  # Pass datetime object directly, not ISO string
            )
        else:
            history_objs = trakt_main.Trakt['sync/history'].get(pagination=True, per_page=100, extended='full')
        print("API call successful, processing results...")
        
        socket.setdefaulttimeout(old_timeout)  # Restore original timeout
    except socket.timeout as e:
        print(f"Timeout error fetching history from Trakt API: {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(f'API timeout - check network connection: {e}')
    except Exception as e:
        print(f"Error fetching history from Trakt API: {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(f'Failed to fetch history: {e}')
    
    if history_objs is None:
        raise SystemExit('Trakt API returned None - check authentication token or API status')
    
    history = []
    seen = 0
    print(f"Processing history items...")
    for item in history_objs:
        d = item.to_dict()
        d['force_type'] = 'movie' if type(item).__name__ == 'Movie' else 'episode'
        d['watched_at_iso'] = item.watched_at.isoformat() if getattr(item, 'watched_at', None) else None
        if d['force_type'] == 'episode':
            d['extracted_show_title'] = item.show.title if hasattr(item, 'show') and item.show else None
            if hasattr(item, 'episode') and item.episode:
                d['extracted_season'] = item.episode.season
        # include full show dict (with ids) when available to help season resolution
        if hasattr(item, 'show') and item.show:
            try:
                d['show'] = item.show.to_dict()
            except Exception:
                d['show'] = {'title': item.show.title}
        history.append(d)
        seen += 1
        if args.limit and seen >= args.limit:
            if args.verbose:
                print(f'--limit reached: {seen} items')
            break
    
    print(f"Fetched {len(history)} new items from Trakt")
    
    # Merge with cached items for incremental updates
    if cached_items:
        print(f"Merging {len(history)} new items with {len(cached_items)} cached items...")
        # Combine new and cached, keeping new items first
        history = history + cached_items
        print(f"Total items after merge: {len(history)}")

    print("\n=== Deduplicating entries ===")
    # Remove obvious duplicates: keep first occurrence of items with the same
    # (force_type, trakt id or title fallback, watched_at_iso). This avoids
    # showing the same movie twice when Trakt returned duplicates.
    deduped = []
    seen_keys = set()
    for it in history:
        trakt_id = None
        try:
            trakt_id = (it.get('ids') or {}).get('trakt')
        except Exception:
            trakt_id = None
        key_id = str(trakt_id) if trakt_id is not None else (it.get('title') or '')

        # Normalize watched timestamp to calendar day (YYYY-MM-DD) for dedupe keys.
        watched_raw = it.get('watched_at_iso') or it.get('watched_at') or it.get('watched_at_str')
        watched_day = None
        if watched_raw:
            try:
                wr = watched_raw
                if isinstance(wr, str) and wr.endswith('Z'):
                    wr = wr[:-1] + '+00:00'
                dt = datetime.fromisoformat(wr) if isinstance(wr, str) else (wr if isinstance(wr, datetime) else None)
                if isinstance(dt, datetime):
                    try:
                        local_dt = dt.astimezone()
                    except Exception:
                        local_dt = dt
                    watched_day = local_dt.date().isoformat()
            except Exception:
                try:
                    # fallback: extract YYYY-MM-DD prefix from string
                    watched_day = str(watched_raw)[:10]
                except Exception:
                    watched_day = None

        key = (it.get('force_type'), key_id, watched_day)
        if key in seen_keys:
            if args.verbose:
                print(f'duplicate skipped: {key}')
            continue
        seen_keys.add(key)
        deduped.append(it)

    print(f"After deduplication: {len(deduped)} items (removed {len(history) - len(deduped)} duplicates)")

    # Exit early if no new items - cache is already up to date
    if start_at and len(deduped) == len(cached_items):
        print('\nNo new items found since last update.')
        print('Cache is already up to date. Use --force to reprocess anyway.')
        return

    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)

    # Smart incremental processing: identify which items are new vs cached
    new_items = []
    cached_item_keys = set()
    
    if cached_items and not args.force:
        # Build a set of keys from cached items
        for cached_item in cached_items:
            trakt_id = None
            try:
                trakt_id = (cached_item.get('ids') or {}).get('trakt')
            except Exception:
                pass
            key_id = str(trakt_id) if trakt_id is not None else (cached_item.get('title') or '')
            watched_raw = cached_item.get('watched_at_iso') or cached_item.get('watched_at')
            watched_day = None
            if watched_raw:
                try:
                    watched_day = str(watched_raw)[:10]
                except Exception:
                    pass
            key = (cached_item.get('force_type'), key_id, watched_day)
            cached_item_keys.add(key)
        
        # Identify new items
        for it in deduped:
            trakt_id = None
            try:
                trakt_id = (it.get('ids') or {}).get('trakt')
            except Exception:
                pass
            key_id = str(trakt_id) if trakt_id is not None else (it.get('title') or '')
            watched_raw = it.get('watched_at_iso') or it.get('watched_at')
            watched_day = None
            if watched_raw:
                try:
                    watched_day = str(watched_raw)[:10]
                except Exception:
                    pass
            key = (it.get('force_type'), key_id, watched_day)
            
            if key not in cached_item_keys:
                new_items.append(it)
        
        print(f"Identified {len(new_items)} new items to process (will reuse {len(cached_items)} from cache)")
    else:
        # No cache or force flag - process everything
        new_items = deduped
        print(f"Processing all {len(new_items)} items")

    # Only process new items
    print("\n=== Processing new items (normalization and image fetching) ===")
    history = new_items

    # normalize
    def normalize(item):
        out = {}
        watched = item.get('watched_at_iso') or item.get('watched_at_str') or item.get('watched_at')

        # Format watched timestamp to `YYYY-MM-DD HH:MM` in local timezone when possible
        def format_watched(s):
            if not s:
                return None
            if isinstance(s, datetime):
                try:
                    return s.astimezone().strftime('%Y-%m-%d %H:%M')
                except Exception:
                    return s.strftime('%Y-%m-%d %H:%M')
            if isinstance(s, str):
                try:
                    ss = s
                    # Normalize 'Z' to +00:00 for fromisoformat
                    if ss.endswith('Z'):
                        ss = ss[:-1] + '+00:00'
                    dt = datetime.fromisoformat(ss)
                    try:
                        local_dt = dt.astimezone()
                    except Exception:
                        local_dt = dt
                    return local_dt.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    return s
            return str(s)

        out['watched_at'] = format_watched(watched)
        is_movie = False
        if item.get('force_type') == 'movie' or item.get('class_name') == 'Movie':
            is_movie = True
        if 'movie' in item and item.get('movie'):
            is_movie = True
        if is_movie:
            m = item.get('movie') or item
            out.update({
                'type': 'movie',
                'title': m.get('title') or item.get('title'),
                'year': m.get('year') or item.get('year'),
                'ids': m.get('ids') or item.get('ids'),
                'runtime': m.get('runtime') or item.get('runtime'),
                'rating': m.get('rating') or item.get('rating'),
                'genres': m.get('genres') or item.get('genres'),
                'cast': item.get('cast', []),
            })
            # include thumbnail if available
            if item.get('thumbnail'):
                out['thumbnail'] = item.get('thumbnail')
            # round rating to one decimal when numeric
            if out.get('rating') is not None:
                try:
                    out['rating'] = round(float(out['rating']), 1)
                except Exception:
                    pass
        else:
            ep = item.get('episode') or item
            season = item.get('extracted_season') if item.get('extracted_season') is not None else (ep.get('season') if isinstance(ep, dict) else None) or item.get('season')
            season = season if season is not None else 1
            number = (ep.get('number') if isinstance(ep, dict) and ep.get('number') is not None else item.get('number'))
            # Use show rating (cached from show details) instead of individual episode rating
            rating = item.get('show_rating') or ep.get('rating') or item.get('rating')
            out.update({
                'type': 'episode',
                'title': ep.get('title') or item.get('title'),
                'season': season,
                'number': number,
                'ids': ep.get('ids') or item.get('ids'),
                'runtime': ep.get('runtime') or item.get('runtime'),
                'rating': rating,
                'show': {'title': (item.get('show') or {}).get('title') or item.get('extracted_show_title')},
                'genres': (item.get('show') or {}).get('genres') or item.get('genres'),
                'year': (item.get('show') or {}).get('year') or item.get('year'),
                'cast': item.get('cast', []),
            })
            # include thumbnail if available
            if item.get('thumbnail'):
                out['thumbnail'] = item.get('thumbnail')
            # round rating to one decimal when numeric
            if out.get('rating') is not None:
                try:
                    out['rating'] = round(float(out['rating']), 1)
                except Exception:
                    pass
        return out

    # Load local .env to get TRAKT_CLIENT_ID for search fallback
    load_dotenv(os.path.join(TRAKT_DIR, '.env'))
    TRAKT_CLIENT_ID = os.getenv('TRAKT_CLIENT_ID')
    RPDB_API_KEY = os.getenv('RPDB_API_KEY')

    print(f"\n=== Starting item processing (total: {len(history)} items) ===")
    if not args.no_images and RPDB_API_KEY:
        print("RPDB image fetching enabled")
    else:
        print("Image fetching disabled")
    
    # Attempt to resolve missing seasons by querying show seasons when possible
    show_cache = {}
    show_details = {}
    movie_details = {}
    show_cast = {}
    movie_cast = {}
    
    processed_count = 0
    for it in history:
        processed_count += 1
        if processed_count % 50 == 0:
            print(f"  Processing: {processed_count}/{len(history)} items...")
        
        if it.get('force_type') == 'episode':
            # prefer extracted_season if present
            if it.get('extracted_season') is not None:
                it['resolved_season'] = it.get('extracted_season')
                continue

            # if season present at top-level, use it
            if it.get('season') is not None:
                it['resolved_season'] = it.get('season')
                continue

            # try to resolve using show ids
            show = it.get('show') or {}
            show_ids = show.get('ids') if isinstance(show, dict) else None
            show_trakt_id = None
            if show_ids and isinstance(show_ids, dict):
                show_trakt_id = show_ids.get('trakt')

            if show_trakt_id:
                if show_trakt_id not in show_cache:
                    try:
                        seasons = trakt_main.Trakt[f'shows/{show_trakt_id}/seasons'].get(extended='episodes')
                    except Exception:
                        seasons = None
                    show_cache[show_trakt_id] = seasons

                seasons = show_cache.get(show_trakt_id)
                if seasons:
                    found = None
                    ep_trakt_id = it.get('ids', {}).get('trakt')
                    for s in seasons:
                        # seasons entries from api may include 'episodes'
                        episodes = s.get('episodes') or []
                        for ep in episodes:
                            # compare IDs as strings to avoid int/str mismatches
                            if ep_trakt_id and str(ep.get('ids', {}).get('trakt')) == str(ep_trakt_id):
                                found = s.get('number')
                                break
                        if found is not None:
                            break
                    if found is not None:
                        it['resolved_season'] = found
                        continue

            # If we couldn't resolve via embedded show ids, try searching Trakt by show title (public search)
            if not show_trakt_id:
                title = it.get('extracted_show_title') or (it.get('show') or {}).get('title')
                if title and TRAKT_CLIENT_ID:
                    try:
                        q = urllib.parse.quote_plus(title)
                        url = f"https://api.trakt.tv/search/show?query={q}"
                        headers = {
                            'Content-Type': 'application/json',
                            'trakt-api-version': '2',
                            'trakt-api-key': TRAKT_CLIENT_ID,
                        }
                        r = requests.get(url, headers=headers, timeout=10)
                        if r.status_code == 200:
                            results = r.json()
                            if results:
                                # try to pick the correct show from search results by
                                # checking seasons/episodes for a matching episode id,
                                # or matching episode title / first_aired date as fallback
                                ep_trakt_id = it.get('ids', {}).get('trakt')
                                ep_title = (it.get('title') or '').strip().lower()
                                ep_first_aired = it.get('first_aired')
                                candidate = None
                                for res in results:
                                    cand_id = res.get('show', {}).get('ids', {}).get('trakt')
                                    if not cand_id:
                                        continue
                                    # fetch seasons for candidate if not cached
                                    if cand_id not in show_cache:
                                        try:
                                            seasons_cand = trakt_main.Trakt[f'shows/{cand_id}/seasons'].get(extended='episodes')
                                        except Exception:
                                            seasons_cand = None
                                        show_cache[cand_id] = seasons_cand

                                    seasons_cand = show_cache.get(cand_id)
                                    if not seasons_cand:
                                        continue
                                    found = False
                                    for s in seasons_cand:
                                        for ep in (s.get('episodes') or []):
                                            # compare trakt ids first
                                            if ep_trakt_id and str(ep.get('ids', {}).get('trakt')) == str(ep_trakt_id):
                                                candidate = cand_id
                                                found = True
                                                break
                                            # fallback: compare episode title
                                            if ep_title and ep.get('title') and ep.get('title').strip().lower() == ep_title:
                                                candidate = cand_id
                                                found = True
                                                break
                                            # fallback: compare first_aired (date/time string equality)
                                            if ep_first_aired and ep.get('first_aired') and ep.get('first_aired') == ep_first_aired:
                                                candidate = cand_id
                                                found = True
                                                break
                                        if found:
                                            break
                                    if candidate:
                                        show_trakt_id = candidate
                                        break
                    except Exception:
                        show_trakt_id = None

                if show_trakt_id and show_trakt_id not in show_cache:
                    try:
                        seasons = trakt_main.Trakt[f'shows/{show_trakt_id}/seasons'].get(extended='episodes')
                    except Exception:
                        seasons = None
                    show_cache[show_trakt_id] = seasons

                seasons = show_cache.get(show_trakt_id)
                if seasons:
                    found = None
                    ep_trakt_id = it.get('ids', {}).get('trakt')
                    for s in seasons:
                        episodes = s.get('episodes') or []
                        for ep in episodes:
                            # compare IDs as strings to avoid int/str mismatches
                            if ep_trakt_id and str(ep.get('ids', {}).get('trakt')) == str(ep_trakt_id):
                                found = s.get('number')
                                break
                        if found is not None:
                            break
                    if found is not None:
                        it['resolved_season'] = found
                        continue

            # Direct episode lookup fallback: try the public episode endpoint by trakt id
            ep_trakt_id = it.get('ids', {}).get('trakt')
            if ep_trakt_id and TRAKT_CLIENT_ID:
                try:
                    # public Trakt API episode lookup (requires client id header)
                    ep_url = f"https://api.trakt.tv/episodes/{ep_trakt_id}?extended=full"
                    headers = {
                        'Content-Type': 'application/json',
                        'trakt-api-version': '2',
                        'trakt-api-key': TRAKT_CLIENT_ID,
                    }
                    r_ep = requests.get(ep_url, headers=headers, timeout=10)
                    if r_ep.status_code == 200:
                        ep_data = r_ep.json()
                        season_num = ep_data.get('season')
                        if season_num is not None:
                            it['resolved_season'] = season_num
                            continue
                except Exception:
                    # silent fallback to existing logic
                    pass

            # fallback: leave resolved_season as None
            it['resolved_season'] = None

    # inject resolved season into items before normalization
    for it in history:
        if it.get('force_type') == 'episode':
            if it.get('resolved_season') is not None:
                it['extracted_season'] = it.get('resolved_season')

    # Attach thumbnail URLs - optimized with show-level caching
    # For episodes: all episodes of the same show share the same poster (much faster)
    # For movies: each movie gets its own poster
    # Use RPDB for both (no API calls, instant) - some show posters may be placeholders but it's fast
    show_poster_cache = {}  # Cache posters by show trakt_id
    show_ids_cache = {}  # Cache show IDs by show title
    show_rating_cache = {}  # Cache ratings by show trakt_id
    
    print(f"\n=== Building image URLs ({'disabled' if args.no_images else 'RPDB'}) ===")
    
    # First, collect show titles that need IDs
    if not args.no_images:
        shows_needing_ids = {}
        for it in history:
            if it.get('force_type') == 'episode':
                show = it.get('show') or {}
                show_ids = show.get('ids') if isinstance(show, dict) else None
                show_title = show.get('title') if isinstance(show, dict) else None
                
                # If show IDs are empty or missing, we need to fetch them
                if show_title and (not show_ids or not show_ids.get('trakt')):
                    if show_title not in shows_needing_ids:
                        shows_needing_ids[show_title] = show
        
        # Fetch show IDs for shows that don't have them
        if shows_needing_ids and TRAKT_CLIENT_ID:
            print(f"  Looking up IDs for {len(shows_needing_ids)} shows...")
            for show_title in shows_needing_ids:
                try:
                    q = urllib.parse.quote_plus(show_title)
                    url = f"https://api.trakt.tv/search/show?query={q}"
                    headers = {
                        'Content-Type': 'application/json',
                        'trakt-api-version': '2',
                        'trakt-api-key': TRAKT_CLIENT_ID,
                    }
                    r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code == 200:
                        results = r.json()
                        if results:
                            first_show = results[0].get('show', {})
                            show_ids = first_show.get('ids', {})
                            if show_ids:
                                show_ids_cache[show_title] = show_ids
                                if args.verbose:
                                    print(f"  Found IDs for '{show_title}': {show_ids}")
                except Exception as e:
                    if args.verbose:
                        print(f"  Failed to fetch IDs for '{show_title}': {e}")
        
        # Update the original history items with fetched show IDs so they get cached
        if show_ids_cache:
            print(f"  Updating {len(show_ids_cache)} shows with fetched IDs in cache...")
            for it in history:
                if it.get('force_type') == 'episode':
                    show = it.get('show') or {}
                    show_title = show.get('title') if isinstance(show, dict) else None
                    if show_title and show_title in show_ids_cache:
                        # Update the show's IDs in the history item
                        if not isinstance(it.get('show'), dict):
                            it['show'] = {}
                        it['show']['ids'] = show_ids_cache[show_title]
    
    # Build RPDB URLs
    for it in history:
        thumb = None
        
        # For episodes, build and cache show poster URL
        if it.get('force_type') == 'episode' and not args.no_images and RPDB_API_KEY:
            show = it.get('show') or {}
            show_title = show.get('title') if isinstance(show, dict) else None
            show_ids = show.get('ids') if isinstance(show, dict) else None
            
            # Use cached IDs if we fetched them
            if show_title and show_title in show_ids_cache:
                show_ids = show_ids_cache[show_title]
            
            show_trakt_id = show_ids.get('trakt') if show_ids else None
            
            # Check cache first
            if show_trakt_id and show_trakt_id in show_poster_cache:
                thumb = show_poster_cache[show_trakt_id]
            elif show_ids:
                # Build RPDB URL from show IDs (prioritize TVDB for TV shows)
                tvdb_id = show_ids.get('tvdb')
                imdb_id = show_ids.get('imdb')
                tmdb_id = show_ids.get('tmdb')
                
                if tvdb_id:
                    thumb = f'https://api.ratingposterdb.com/{RPDB_API_KEY}/tvdb/poster-default/{tvdb_id}.jpg?fallback=true'
                elif imdb_id:
                    thumb = f'https://api.ratingposterdb.com/{RPDB_API_KEY}/imdb/poster-default/{imdb_id}.jpg?fallback=true'
                elif tmdb_id:
                    thumb = f'https://api.ratingposterdb.com/{RPDB_API_KEY}/tmdb/poster-default/series-{tmdb_id}.jpg?fallback=true'
                
                # Cache for reuse
                if show_trakt_id and thumb:
                    show_poster_cache[show_trakt_id] = thumb
        
        # For movies, build RPDB URL from movie IDs
        elif it.get('force_type') == 'movie' and not args.no_images and RPDB_API_KEY:
            movie = it.get('movie') or it
            ids = movie.get('ids') if isinstance(movie, dict) else None
            if ids and isinstance(ids, dict):
                imdb_id = ids.get('imdb')
                tmdb_id = ids.get('tmdb')
                tvdb_id = ids.get('tvdb')
                
                if imdb_id:
                    thumb = f'https://api.ratingposterdb.com/{RPDB_API_KEY}/imdb/poster-default/{imdb_id}.jpg?fallback=true'
                elif tmdb_id:
                    thumb = f'https://api.ratingposterdb.com/{RPDB_API_KEY}/tmdb/poster-default/movie-{tmdb_id}.jpg?fallback=true'
                elif tvdb_id:
                    thumb = f'https://api.ratingposterdb.com/{RPDB_API_KEY}/tvdb/poster-default/{tvdb_id}.jpg?fallback=true'
                
                if args.verbose and thumb:
                    print(f'Movie poster: {thumb}')

        if thumb:
            it['thumbnail'] = thumb
    
    print(f"  Cached {len(show_poster_cache)} unique show posters")

    # Fetch show ratings for episodes (lightweight - just ratings, no full enrichment)
    # This runs even with --no-enrichment to optimize rating data
    print("\n=== Fetching show ratings for episodes ===")
    show_title_to_id_ratings = {}
    for it in history:
        if it.get('force_type') == 'episode':
            show = it.get('show') or {}
            show_title = show.get('title') if isinstance(show, dict) else None
            if not show_title:
                show_title = it.get('extracted_show_title')
            
            if show_title and show_title not in show_title_to_id_ratings:
                show_ids = show.get('ids') if isinstance(show, dict) else None
                if show_ids and isinstance(show_ids, dict):
                    show_trakt_id = show_ids.get('trakt')
                    if show_trakt_id:
                        show_title_to_id_ratings[show_title] = show_trakt_id
    
    # Fetch just the rating for each show (minimal API call)
    for show_title, show_trakt_id in show_title_to_id_ratings.items():
        if show_trakt_id not in show_rating_cache:
            try:
                # Fetch show with minimal extended parameter - just need rating
                show_obj = trakt_main.Trakt[f'shows/{show_trakt_id}'].get()
                rating = None
                if hasattr(show_obj, 'rating'):
                    rating = show_obj.rating
                elif hasattr(show_obj, 'get'):
                    rating = show_obj.get('rating')
                elif hasattr(show_obj, '__dict__'):
                    rating = vars(show_obj).get('rating')
                
                if rating is not None:
                    # Convert to float to ensure JSON serialization works
                    try:
                        rating = float(rating)
                        show_rating_cache[show_trakt_id] = rating
                    except (ValueError, TypeError):
                        pass
            except Exception:
                pass
    
    # Apply cached show ratings to episodes
    for it in history:
        if it.get('force_type') == 'episode':
            show = it.get('show') or {}
            show_title = show.get('title') if isinstance(show, dict) else None
            if not show_title:
                show_title = it.get('extracted_show_title')
            
            if show_title:
                show_trakt_id = show_title_to_id_ratings.get(show_title)
                if show_trakt_id and show_trakt_id in show_rating_cache:
                    it['show_rating'] = show_rating_cache[show_trakt_id]
    
    print(f"  Cached {len(show_rating_cache)} show ratings (will be reused for all episodes)")

    # Enrich episodes with show details (genres and year)
    # Build a show title to trakt_id mapping for episodes
    if not getattr(args, 'no_enrichment', False):
        print("\n=== Enriching episodes with show metadata ===")
        show_title_to_id = {}
        for it in history:
            if it.get('force_type') == 'episode':
                show = it.get('show') or {}
                show_title = show.get('title') if isinstance(show, dict) else None
                if not show_title:
                    show_title = it.get('extracted_show_title')
                
                if show_title and show_title not in show_title_to_id:
                    # Try to search for the show to get its trakt ID
                    if TRAKT_CLIENT_ID:
                        try:
                            q = urllib.parse.quote_plus(show_title)
                            url = f"https://api.trakt.tv/search/show?query={q}"
                            headers = {
                                'Content-Type': 'application/json',
                                'trakt-api-version': '2',
                                'trakt-api-key': TRAKT_CLIENT_ID,
                            }
                            r = requests.get(url, headers=headers, timeout=10)
                            if r.status_code == 200:
                                results = r.json()
                                if results:
                                    # Take the first result (best match)
                                    first_show = results[0].get('show', {})
                                    show_trakt_id = first_show.get('ids', {}).get('trakt')
                                    if show_trakt_id:
                                        show_title_to_id[show_title] = show_trakt_id
                        except Exception:
                            pass
        
        # Now fetch show details for all discovered show IDs
        for show_trakt_id in show_title_to_id.values():
            if show_trakt_id not in show_details:
                try:
                    show_obj = trakt_main.Trakt[f'shows/{show_trakt_id}'].get(extended='full,images')
                    # Convert Trakt Show object to dict
                    if hasattr(show_obj, 'to_dict'):
                        sd = show_obj.to_dict()
                    elif hasattr(show_obj, '__dict__'):
                        sd = vars(show_obj)
                    else:
                        sd = dict(show_obj) if show_obj else {}
                    show_details[show_trakt_id] = sd
                    # Cache show rating for use in episodes (convert to float for JSON)
                    if sd and sd.get('rating') is not None:
                        try:
                            show_rating_cache[show_trakt_id] = float(sd.get('rating'))
                        except (ValueError, TypeError):
                            pass
                except Exception:
                    show_details[show_trakt_id] = None
        
        # Finally, enrich episodes with show metadata
        enriched_count = 0
        for it in history:
            if it.get('force_type') == 'episode':
                show = it.get('show') or {}
                show_title = show.get('title') if isinstance(show, dict) else None
                if not show_title:
                    show_title = it.get('extracted_show_title')
                
                show_trakt_id = show_title_to_id.get(show_title) if show_title else None
                if show_trakt_id and show_trakt_id in show_details:
                    sd = show_details.get(show_trakt_id) or {}
                    if isinstance(sd, dict):
                        # Add genres from show details
                        if sd.get('genres') and not it.get('genres'):
                            it['genres'] = sd.get('genres')
                            enriched_count += 1
                        # Add year from show details
                        if sd.get('year') and not it.get('year'):
                            it['year'] = sd.get('year')
                        # Cache show rating from full enrichment if available and not already cached
                        if sd.get('rating') is not None and show_trakt_id not in show_rating_cache:
                            try:
                                rating_val = float(sd.get('rating'))
                                show_rating_cache[show_trakt_id] = rating_val
                                it['show_rating'] = rating_val
                            except (ValueError, TypeError):
                                pass
                        # Update show object with genres and year for normalization
                        if not isinstance(it.get('show'), dict):
                            it['show'] = {}
                        it['show']['genres'] = sd.get('genres')
                        it['show']['year'] = sd.get('year')
        
        print(f"  Enriched {enriched_count} episodes with show metadata")
    else:
        print("\n=== Skipping show enrichment (--no-enrichment) ===")

    # Fetch cast/actors for movies and shows (optional - can be disabled with --no-cast flag)
    if not getattr(args, 'no_cast', False):
        print("\n=== Fetching cast information ===")
        headers = {
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': TRAKT_CLIENT_ID
        }
        
        # Count unique items to fetch
        unique_movies = set()
        unique_shows = set()
        for it in history:
            if it.get('force_type') == 'movie':
                movie_id = it.get('ids', {}).get('trakt')
                if movie_id and movie_id not in movie_cast:
                    unique_movies.add(movie_id)
            elif it.get('force_type') == 'episode':
                show = it.get('show') or {}
                show_title = show.get('title') if isinstance(show, dict) else None
                if not show_title:
                    show_title = it.get('extracted_show_title')
                show_id = show_title_to_id.get(show_title) if show_title else None
                if show_id and show_id not in show_cast:
                    unique_shows.add(show_id)
        
        print(f"Fetching cast for {len(unique_movies)} movies and {len(unique_shows)} shows...")
        
        fetched_movies = 0
        fetched_shows = 0
        for it in history:
            if it.get('force_type') == 'movie':
                movie_trakt_id = it.get('ids', {}).get('trakt')
                if movie_trakt_id and movie_trakt_id not in movie_cast:
                    try:
                        url = f'https://api.trakt.tv/movies/{movie_trakt_id}/people'
                        r = requests.get(url, headers=headers, timeout=10)
                        if r.status_code == 200:
                            data = r.json()
                            cast_list = data.get('cast', [])
                            top_cast = []
                            for c in cast_list[:5]:
                                person = c.get('person', {})
                                name = person.get('name')
                                if name:
                                    top_cast.append(name)
                            movie_cast[movie_trakt_id] = top_cast
                            fetched_movies += 1
                            if fetched_movies % 10 == 0:
                                print(f"  Progress: {fetched_movies}/{len(unique_movies)} movies")
                        else:
                            movie_cast[movie_trakt_id] = []
                    except Exception as e:
                        movie_cast[movie_trakt_id] = []
                        if args.verbose:
                            print(f"  Error fetching cast for movie {movie_trakt_id}: {e}")
            
            elif it.get('force_type') == 'episode':
                show = it.get('show') or {}
                show_title = show.get('title') if isinstance(show, dict) else None
                if not show_title:
                    show_title = it.get('extracted_show_title')
                
                show_trakt_id = show_title_to_id.get(show_title) if show_title else None
                if show_trakt_id and show_trakt_id not in show_cast:
                    try:
                        url = f'https://api.trakt.tv/shows/{show_trakt_id}/people'
                        r = requests.get(url, headers=headers, timeout=10)
                        if r.status_code == 200:
                            data = r.json()
                            cast_list = data.get('cast', [])
                            top_cast = []
                            for c in cast_list[:5]:
                                person = c.get('person', {})
                                name = person.get('name')
                                if name:
                                    top_cast.append(name)
                            show_cast[show_trakt_id] = top_cast
                            fetched_shows += 1
                            if fetched_shows % 5 == 0:
                                print(f"  Progress: {fetched_shows}/{len(unique_shows)} shows")
                        else:
                            show_cast[show_trakt_id] = []
                    except Exception as e:
                        show_cast[show_trakt_id] = []
                        if args.verbose:
                            print(f"  Error fetching cast for show {show_trakt_id}: {e}")

        # Add cast to items
        print("\n=== Adding cast to items ===")
        cast_added = 0
        for it in history:
            if it.get('force_type') == 'movie':
                movie_trakt_id = it.get('ids', {}).get('trakt')
                if movie_trakt_id and movie_trakt_id in movie_cast:
                    it['cast'] = movie_cast[movie_trakt_id]
                    if movie_cast[movie_trakt_id]:
                        cast_added += 1
            elif it.get('force_type') == 'episode':
                show = it.get('show') or {}
                show_title = show.get('title') if isinstance(show, dict) else None
                if not show_title:
                    show_title = it.get('extracted_show_title')
                
                show_trakt_id = show_title_to_id.get(show_title) if show_title else None
                if show_trakt_id and show_trakt_id in show_cast:
                    it['cast'] = show_cast[show_trakt_id]
                    if show_cast[show_trakt_id]:
                        cast_added += 1
        
        print(f"Added cast to {cast_added} items")
    else:
        print("\n=== Skipping cast fetch (--no-cast flag) ===")

    # Normalize newly processed items
    simplified_new = [normalize(i) for i in history]
    
    # Load previously processed items from output cache if available
    simplified = simplified_new
    if cached_items and len(new_items) < len(deduped):
        # We have cached items - need to merge
        print(f"\n=== Merging {len(simplified_new)} new processed items with cache ===")
        
        # Load the existing processed output
        if os.path.exists(OUT_PATH):
            try:
                with open(OUT_PATH, 'r') as f:
                    cached_output = json.load(f)
                    cached_processed_items = cached_output.get('items', [])
                
                # Build a set of keys from new items to avoid duplicates
                new_item_keys = set()
                for item in simplified_new:
                    # Use same key logic as deduplication
                    trakt_id = (item.get('ids') or {}).get('trakt')
                    key_id = str(trakt_id) if trakt_id else (item.get('title') or '')
                    watched_day = str(item.get('watched_at') or '')[:10]
                    key = (item.get('type'), key_id, watched_day)
                    new_item_keys.add(key)
                
                # Merge: new items + cached items (excluding any that are in new)
                simplified = simplified_new.copy()
                for cached_item in cached_processed_items:
                    trakt_id = (cached_item.get('ids') or {}).get('trakt')
                    key_id = str(trakt_id) if trakt_id else (cached_item.get('title') or '')
                    watched_day = str(cached_item.get('watched_at') or '')[:10]
                    key = (cached_item.get('type'), key_id, watched_day)
                    
                    if key not in new_item_keys:
                        simplified.append(cached_item)
                
                print(f"  Total items after merge: {len(simplified)} ({len(simplified_new)} new + {len(simplified) - len(simplified_new)} cached)")
            except Exception as e:
                print(f"  Warning: Could not load cached processed items: {e}")
                print(f"  Using only newly processed items")
                simplified = simplified_new
    
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    
    end_time = datetime.now()
    generation_time_seconds = (end_time - start_time).total_seconds()
    
    out = {
        'generated_at': datetime.now().isoformat(),
        'generation_time': round(generation_time_seconds, 2),
        'count': len(simplified),
        'items': simplified
    }
    
    # Write all files at once (minimize disk I/O for slow SD cards)
    print("\n=== Writing output files ===")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)
    
    # Write raw data first (for caching) - save ALL deduped items (new + cached)
    with open(RAW_PATH, 'w') as f:
        json.dump(deduped, f, indent=2)
    print(f'Wrote raw data: {RAW_PATH}')
    
    # Write processed output
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, indent=2)
    print(f'Wrote processed data: {OUT_PATH}')
    
    print(f'Generation time: {generation_time_seconds:.2f} seconds')


if __name__ == '__main__':
    main()
