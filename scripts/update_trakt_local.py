#!/usr/bin/env python3
import os
import json
from datetime import datetime
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

import sys
if TRAKT_DIR not in sys.path:
    sys.path.insert(0, TRAKT_DIR)
import trakt_scraper
import tmdb_enrich

# Load environment to get primary user
load_dotenv(os.path.join(TRAKT_DIR, '.env'))
PRIMARY_USER = os.getenv('PRIMARY_USER')
if not PRIMARY_USER:
    raise SystemExit("PRIMARY_USER must be set in .env file")

print(f"update_trakt_local.py: using TRAKT_DIR={TRAKT_DIR}, PRIMARY_USER={PRIMARY_USER}")


def get_user_paths(username: str = None):
    """Get raw and output paths for a user. If username is None, uses primary user."""
    if username is None:
        username = PRIMARY_USER

    if username == PRIMARY_USER:
        # Primary user uses default paths for backward compatibility
        raw_path = os.path.join(TRAKT_DIR, '_data', 'trakt_raw.json')
        out_path = os.path.join(TRAKT_DIR, '_data', 'trakt_history.json')
    else:
        # Other users get prefixed files
        raw_path = os.path.join(TRAKT_DIR, '_data', f'trakt_raw_{username}.json')
        out_path = os.path.join(TRAKT_DIR, '_data', f'trakt_history_{username}.json')

    return raw_path, out_path


def _image_url(path):
    """Trakt image fields are protocol-relative CDN paths (e.g.
    'media.trakt.tv/images/movies/.../posters/medium/x.jpg.webp')."""
    if not path:
        return None
    if path.startswith('http'):
        return path
    return f'https://{path}'


def main():
    start_time = datetime.now()

    parser = argparse.ArgumentParser(description='Update local Trakt history from scraped public profile data')
    parser.add_argument('--user', type=str, default=PRIMARY_USER, help=f'Username to update (default: {PRIMARY_USER})')
    parser.add_argument('--limit', type=int, default=0, help='Limit number of history items processed (0 = all)')
    parser.add_argument('--no-cast', action='store_true', help='Do not fetch cast information from TMDB (much faster)')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('--force', action='store_true', help='Force reprocessing even if raw data unchanged')
    args = parser.parse_args()

    username = args.user
    RAW_PATH, OUT_PATH = get_user_paths(username)
    print(f"Updating user: {username}")
    print(f"  Raw cache: {RAW_PATH}")
    print(f"  Output: {OUT_PATH}")

    # Load existing cache so enrichment can stay incremental (only genuinely-new
    # items get re-enriched downstream).
    cached_items = []
    if os.path.exists(RAW_PATH) and not args.force:
        try:
            with open(RAW_PATH, 'r') as f:
                cached_items = json.load(f)
            if cached_items:
                print(f"Found {len(cached_items)} cached items; enrichment will run only for new items.")
        except Exception as e:
            print(f"Could not read cache: {e}")
            cached_items = []

    print(f"Scraping public watch history for {username} from trakt.tv...")
    try:
        history_objs = trakt_scraper.get_history(username, verbose=args.verbose)
    except Exception as e:
        print(f"Error scraping history from Trakt: {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(f'Failed to scrape history: {e}')

    if not history_objs:
        print("WARNING: No items scraped from Trakt (profile may be private, or username not found)")
        history_objs = []

    print(f"Scraped {len(history_objs)} items from Trakt")

    history = []
    seen = 0
    print("\nProcessing history items...")
    for d in history_objs:
        # Raw JSON from the scraped public history endpoint: has 'movie' or
        # 'episode' (+ 'show' for episodes), 'watched_at', 'type'.
        if 'movie' in d and d['movie']:
            d['force_type'] = 'movie'
            if 'ids' not in d and isinstance(d['movie'], dict):
                d['ids'] = d['movie'].get('ids')
        elif 'episode' in d and d['episode']:
            d['force_type'] = 'episode'
            if 'ids' not in d and isinstance(d['episode'], dict):
                d['ids'] = d['episode'].get('ids')
        else:
            continue  # Skip unknown types

        if 'watched_at' in d:
            d['watched_at_iso'] = d['watched_at']

        if d['force_type'] == 'episode':
            show = d.get('show') or {}
            d['extracted_show_title'] = show.get('title')
            episode = d.get('episode') or {}
            d['extracted_season'] = episode.get('season')

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

        # For episodes, include season and episode number to allow multiple episodes of same show on same day
        episode_identifier = None
        if it.get('force_type') == 'episode':
            episode_data = it.get('episode', {})
            season = episode_data.get('season')
            number = episode_data.get('number')
            if season is not None and number is not None:
                episode_identifier = f"S{season}E{number}"

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
                    watched_day = str(watched_raw)[:10]
                except Exception:
                    watched_day = None

        key = (it.get('force_type'), key_id, episode_identifier, watched_day)
        if key in seen_keys:
            if args.verbose:
                print(f'duplicate skipped: {key}')
            continue
        seen_keys.add(key)
        deduped.append(it)

    print(f"After deduplication: {len(deduped)} items (removed {len(history) - len(deduped)} duplicates)")

    if cached_items and len(deduped) == len(cached_items):
        print('\nNo new items found since last update.')

    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)

    # Smart incremental processing: identify which items are new vs cached
    new_items = []

    if cached_items and not args.force:
        cached_item_keys = set()
        for cached_item in cached_items:
            trakt_id = None
            try:
                trakt_id = (cached_item.get('ids') or {}).get('trakt')
            except Exception:
                pass
            key_id = str(trakt_id) if trakt_id is not None else (cached_item.get('title') or '')
            watched_raw = cached_item.get('watched_at_iso') or cached_item.get('watched_at')
            watched_day = str(watched_raw)[:10] if watched_raw else None
            key = (cached_item.get('force_type'), key_id, watched_day)
            cached_item_keys.add(key)

        for it in deduped:
            trakt_id = None
            try:
                trakt_id = (it.get('ids') or {}).get('trakt')
            except Exception:
                pass
            key_id = str(trakt_id) if trakt_id is not None else (it.get('title') or '')
            watched_raw = it.get('watched_at_iso') or it.get('watched_at')
            watched_day = str(watched_raw)[:10] if watched_raw else None
            key = (it.get('force_type'), key_id, watched_day)

            if key not in cached_item_keys:
                new_items.append(it)

        print(f"Identified {len(new_items)} new items to process (will reuse {len(cached_items)} from cache)")
    else:
        new_items = deduped
        print(f"Processing all {len(new_items)} items")

    print("\n=== Fetching cast from TMDB ===")
    history = new_items
    if not args.no_cast:
        for it in history:
            if it.get('force_type') == 'movie':
                movie = it.get('movie') or {}
                tmdb_id = (movie.get('ids') or {}).get('tmdb')
                it['cast'] = tmdb_enrich.get_cast(tmdb_id, 'movie')
            elif it.get('force_type') == 'episode':
                show = it.get('show') or {}
                tmdb_id = (show.get('ids') or {}).get('tmdb')
                it['cast'] = tmdb_enrich.get_cast(tmdb_id, 'show')
        tmdb_enrich.save_cache()
        print(f"  Cast fetched for {len(history)} items")
    else:
        print("  Skipping cast fetch (--no-cast)")

    # normalize
    def normalize(item):
        out = {}
        watched = item.get('watched_at_iso') or item.get('watched_at_str') or item.get('watched_at')

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

        if item.get('force_type') == 'movie':
            m = item.get('movie') or {}
            images = m.get('images') or {}
            poster_list = images.get('poster') or []
            out.update({
                'type': 'movie',
                'title': m.get('title'),
                'year': m.get('year'),
                'ids': m.get('ids'),
                'runtime': m.get('runtime'),
                'rating': item.get('user_rating'),
                'genres': m.get('genres'),
                'cast': item.get('cast', []),
            })
            thumb = _image_url(poster_list[0] if poster_list else None)
            if thumb:
                out['thumbnail'] = thumb
        else:
            ep = item.get('episode') or {}
            show = item.get('show') or {}
            season = item.get('extracted_season') if item.get('extracted_season') is not None else ep.get('season')
            season = season if season is not None else 1
            number = ep.get('number')
            show_images = show.get('images') or {}
            poster_list = show_images.get('poster') or []
            out.update({
                'type': 'episode',
                'title': ep.get('title'),
                'season': season,
                'number': number,
                'ids': ep.get('ids'),
                'runtime': ep.get('runtime') or show.get('runtime'),
                'rating': item.get('user_rating'),
                'show': {'title': show.get('title') or item.get('extracted_show_title')},
                'genres': show.get('genres'),
                'year': show.get('year'),
                'cast': item.get('cast', []),
            })
            thumb = _image_url(poster_list[0] if poster_list else None)
            if thumb:
                out['thumbnail'] = thumb
        return out

    simplified_new = [normalize(i) for i in history]

    simplified = simplified_new
    if cached_items and len(new_items) < len(deduped):
        print(f"\n=== Merging {len(simplified_new)} new processed items with cache ===")
        if os.path.exists(OUT_PATH):
            try:
                with open(OUT_PATH, 'r') as f:
                    cached_output = json.load(f)
                    cached_processed_items = cached_output.get('items', [])

                new_item_keys = set()
                for item in simplified_new:
                    trakt_id = (item.get('ids') or {}).get('trakt')
                    key_id = str(trakt_id) if trakt_id else (item.get('title') or '')
                    watched_day = str(item.get('watched_at') or '')[:10]
                    key = (item.get('type'), key_id, watched_day)
                    new_item_keys.add(key)

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

    rated_count = sum(1 for item in simplified if item.get('rating') is not None)
    print(f"Ratings: {rated_count}/{len(simplified)} items rated in output (ratings are no longer synced from Trakt; existing ratings are preserved)")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    end_time = datetime.now()
    generation_time_seconds = (end_time - start_time).total_seconds()

    out = {
        'generated_at': datetime.now().isoformat(),
        'generation_time': round(generation_time_seconds, 2),
        'count': len(simplified),
        'items': simplified
    }

    print("\n=== Writing output files ===")
    with open(RAW_PATH, 'w') as f:
        json.dump(deduped, f, indent=2)
    print(f'Wrote raw data: {RAW_PATH}')

    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, indent=2)
    print(f'Wrote processed data: {OUT_PATH}')

    print(f'Generation time: {generation_time_seconds:.2f} seconds')


if __name__ == '__main__':
    main()
