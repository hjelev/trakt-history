#!/usr/bin/env python3
import os
import json
import importlib.util
import time
from datetime import datetime
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
    start_time = datetime.utcnow()
    
    # CLI flags for quicker debug runs
    parser = argparse.ArgumentParser(description='Update local Trakt history and thumbnails')
    parser.add_argument('--limit', type=int, default=0, help='Limit number of history items processed (0 = all)')
    parser.add_argument('--no-images', action='store_true', help='Do not fetch images/thumbnails')
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

    history_objs = trakt_main.Trakt['sync/history'].get(pagination=True, per_page=100, extended='full')
    history = []
    seen = 0
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

    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)

    # If the existing raw cache is identical to the newly fetched raw data,
    # skip rewriting and skip the expensive normalization/image work. This
    # provides a full-cache behavior: only re-run normalization when Trakt
    # data actually changed.
    raw_changed = True
    if os.path.exists(RAW_PATH):
        try:
            with open(RAW_PATH, 'r') as f:
                old_raw = json.load(f)
            # Compare canonical JSON (sort keys) to detect changes
            try:
                if json.dumps(old_raw, sort_keys=True) == json.dumps(deduped, sort_keys=True):
                    raw_changed = False
            except Exception:
                # If JSON serialization comparison fails, treat as changed
                raw_changed = True
        except Exception:
            raw_changed = True

    if not raw_changed and not args.force:
        print('Raw Trakt history unchanged; skipping normalization and image fetching.')
        print('Use --force to reprocess anyway.')
        return

    # write new raw file and continue processing
    with open(RAW_PATH, 'w') as f:
        json.dump(deduped, f, indent=2)

    # replace history with deduped list for further processing
    history = deduped

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
            out.update({
                'type': 'episode',
                'title': ep.get('title') or item.get('title'),
                'season': season,
                'number': number,
                'ids': ep.get('ids') or item.get('ids'),
                'runtime': ep.get('runtime') or item.get('runtime'),
                'rating': ep.get('rating') or item.get('rating'),
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

    # Attempt to resolve missing seasons by querying show seasons when possible
    show_cache = {}
    show_details = {}
    movie_details = {}
    show_cast = {}
    movie_cast = {}
    for it in history:
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

    # Attempt to attach thumbnail URLs for episodes and movies by querying
    # Trakt details (extended=images) for shows/movies when available.
    for it in history:
        thumb = None
        # Prefer episode-level images if present
        ep = it.get('episode') or {}
        if isinstance(ep, dict) and ep.get('images'):
            imgs = ep.get('images')
            # try to find first available url in nested dicts
            for v in imgs.values():
                if isinstance(v, dict):
                    for key in ('thumb', 'screenshot', 'poster', 'full'):
                        if v.get(key):
                            thumb = v.get(key)
                            break
                if thumb:
                    break

        # If no episode image, prefer RPDB (RatingPosterDB) if API key is configured
        # RPDB usage format: https://api.ratingposterdb.com/{apiKey}/{mediaType}/poster-default/{mediaId}.jpg
        # mediaType can be 'imdb', 'tmdb' or 'tvdb'. For TMDB use 'movie-{id}' or 'series-{id}'
        if not thumb and RPDB_API_KEY and not args.no_images:
            # try imdb first
            imdb_id = None
            tmdb_id = None
            tvdb_id = None
            
            # For episodes, try to use show IDs if available to get show poster
            # Otherwise fall back to episode IDs
            if it.get('force_type') == 'episode':
                show = it.get('show') or {}
                show_ids = show.get('ids') if isinstance(show, dict) else None
                if show_ids and isinstance(show_ids, dict):
                    imdb_id = show_ids.get('imdb')
                    tmdb_id = show_ids.get('tmdb')
                    tvdb_id = show_ids.get('tvdb')
                
                # If no show IDs, fall back to episode IDs
                if not (imdb_id or tmdb_id or tvdb_id):
                    ids = (it.get('ids') or {})
                    if isinstance(ids, dict):
                        imdb_id = ids.get('imdb')
                        tmdb_id = ids.get('tmdb')
                        tvdb_id = ids.get('tvdb')
            else:
                # For movies, use movie ids
                ids = (it.get('ids') or {})
                if isinstance(ids, dict):
                    imdb_id = ids.get('imdb')
                    tmdb_id = ids.get('tmdb')
                    tvdb_id = ids.get('tvdb')
            # prefer IMDB id when available
            if imdb_id:
                media_type = 'imdb'
                media_id = imdb_id
            elif tmdb_id:
                # need to decide movie vs series; check force_type or show presence
                if it.get('force_type') == 'movie':
                    media_type = 'tmdb'
                    media_id = f'movie-{tmdb_id}'
                else:
                    media_type = 'tmdb'
                    media_id = f'series-{tmdb_id}'
            elif tvdb_id:
                media_type = 'tvdb'
                media_id = tvdb_id
            else:
                media_type = None
                media_id = None

            if media_type and media_id:
                try:
                    # Request a reasonably small poster size to save bandwidth. RPDB supports
                    # size query param (medium/large/verylarge); request `medium` which is the
                    # smallest documented good-quality size.
                    rpdb_url = f'https://api.ratingposterdb.com/{RPDB_API_KEY}/{media_type}/poster-default/{media_id}.jpg?fallback=true&size=medium'
                    # try HEAD first; if the server doesn't support HEAD, fall back to a lightweight GET
                    try:
                        h = requests.head(rpdb_url, timeout=5)
                        if args.verbose:
                            print(f'RPDB HEAD {rpdb_url} -> {getattr(h, "status_code", "ERR")}')
                        if h.status_code == 200:
                            thumb = rpdb_url
                        else:
                            # sized URL failed — try fallback without size parameter
                            fallback_url = f'https://api.ratingposterdb.com/{RPDB_API_KEY}/{media_type}/poster-default/{media_id}.jpg?fallback=true'
                            if args.verbose:
                                print(f'RPDB sized URL failed, trying fallback {fallback_url}')
                            try:
                                h2 = requests.head(fallback_url, timeout=5)
                                if args.verbose:
                                    print(f'RPDB HEAD {fallback_url} -> {getattr(h2, "status_code", "ERR")}')
                                if h2.status_code == 200:
                                    thumb = fallback_url
                                else:
                                    try:
                                        g = requests.get(fallback_url, stream=True, timeout=10)
                                        if args.verbose:
                                            print(f'RPDB GET {fallback_url} -> {getattr(g, "status_code", "ERR")}')
                                        if g.status_code == 200:
                                            thumb = fallback_url
                                        g.close()
                                    except Exception:
                                        if args.verbose:
                                            print(f'RPDB GET failed for fallback {fallback_url}')
                            except Exception:
                                # fallback HEAD failed; try GET on the original sized URL as last resort
                                try:
                                    g = requests.get(rpdb_url, stream=True, timeout=10)
                                    if args.verbose:
                                        print(f'RPDB GET (sized) {rpdb_url} -> {getattr(g, "status_code", "ERR")}')
                                    if g.status_code == 200:
                                        thumb = rpdb_url
                                    g.close()
                                except Exception:
                                    if args.verbose:
                                        print(f'RPDB request error for {rpdb_url}')
                    except Exception:
                        # HEAD itself failed (some servers block HEAD). Try GET as a fallback without size first
                        try:
                            fallback_url = f'https://api.ratingposterdb.com/{RPDB_API_KEY}/{media_type}/poster-default/{media_id}.jpg?fallback=true'
                            g = requests.get(fallback_url, stream=True, timeout=10)
                            if args.verbose:
                                print(f'RPDB GET (no-HEAD, fallback) {fallback_url} -> {getattr(g, "status_code", "ERR")}')
                            if g.status_code == 200:
                                thumb = fallback_url
                            g.close()
                        except Exception:
                            if args.verbose:
                                print(f'RPDB request error for {media_type}/{media_id}')
                except Exception:
                    if args.verbose:
                        print(f'RPDB: unexpected error building URL for {media_type}/{media_id}')

        # If no episode image, try show images (Trakt) if RPDB wasn't available or failed
        if not thumb and it.get('force_type') == 'episode':
            show = it.get('show') or {}
            show_ids = show.get('ids') if isinstance(show, dict) else None
            show_trakt_id = show_ids.get('trakt') if (show_ids and isinstance(show_ids, dict)) else None
            if show_trakt_id:
                if show_trakt_id not in show_details:
                    try:
                        show_details[show_trakt_id] = trakt_main.Trakt[f'shows/{show_trakt_id}'].get(extended='full,images')
                    except Exception:
                        show_details[show_trakt_id] = None
                sd = show_details.get(show_trakt_id) or {}
                imgs = sd.get('images') if isinstance(sd, dict) else None
                if imgs:
                    for v in imgs.values():
                        if isinstance(v, dict):
                            for key in ('thumb', 'poster', 'full'):
                                if v.get(key):
                                    thumb = v.get(key)
                                    break
                        if thumb:
                            break

        # If still no thumb and item is movie, try movie images
        if not thumb and it.get('force_type') == 'movie':
            movie = it.get('movie') or it
            movie_ids = movie.get('ids') if isinstance(movie, dict) else None
            movie_trakt_id = movie_ids.get('trakt') if movie_ids else None
            if movie_trakt_id:
                if movie_trakt_id not in movie_details:
                    try:
                        movie_details[movie_trakt_id] = trakt_main.Trakt[f'movies/{movie_trakt_id}'].get(extended='images')
                    except Exception:
                        movie_details[movie_trakt_id] = None
                md = movie_details.get(movie_trakt_id) or {}
                imgs = md.get('images') if isinstance(md, dict) else None
                if imgs:
                    for v in imgs.values():
                        if isinstance(v, dict):
                            for key in ('thumb', 'poster', 'full'):
                                if v.get(key):
                                    thumb = v.get(key)
                                    break
                        if thumb:
                            break

        if thumb:
            it['thumbnail'] = thumb

    # Enrich episodes with show details (genres and year)
    # Build a show title to trakt_id mapping for episodes
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
                    # Update show object with genres and year for normalization
                    if not isinstance(it.get('show'), dict):
                        it['show'] = {}
                    it['show']['genres'] = sd.get('genres')
                    it['show']['year'] = sd.get('year')

    # Fetch cast/actors for movies and shows
    print("\n=== Fetching cast information ===")
    headers = {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': TRAKT_CLIENT_ID
    }
    
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
                        print(f"  Movie ID {movie_trakt_id}: {len(top_cast)} actors")
                    else:
                        movie_cast[movie_trakt_id] = []
                        print(f"  Movie ID {movie_trakt_id}: API returned {r.status_code}")
                except Exception as e:
                    movie_cast[movie_trakt_id] = []
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
                        print(f"  Show ID {show_trakt_id}: {len(top_cast)} actors")
                    else:
                        show_cast[show_trakt_id] = []
                        print(f"  Show ID {show_trakt_id}: API returned {r.status_code}")
                except Exception as e:
                    show_cast[show_trakt_id] = []
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

    simplified = [normalize(i) for i in history]
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    
    end_time = datetime.utcnow()
    generation_time_seconds = (end_time - start_time).total_seconds()
    
    out = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'generation_time': round(generation_time_seconds, 2),
        'count': len(simplified),
        'items': simplified
    }
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, indent=2)

    print(f'Wrote {OUT_PATH} and {RAW_PATH}')
    print(f'Generation time: {generation_time_seconds:.2f} seconds')


if __name__ == '__main__':
    main()
