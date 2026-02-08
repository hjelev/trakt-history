#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import importlib.util
import time
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, redirect, url_for, flash, request
from math import ceil
from dotenv import load_dotenv
from urllib.parse import quote

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

from urllib.parse import unquote

APP = Flask(__name__, template_folder='templates')
APP.secret_key = os.getenv('FLASK_SECRET', 'dev-secret')

# Import scheduler
try:
    from scheduler import start_scheduler, stop_scheduler
    HAS_SCHEDULER = True
except ImportError:
    HAS_SCHEDULER = False
    print("Warning: APScheduler not available. Background updates disabled.")

# Multi-user configuration
PRIMARY_USER = os.getenv('PRIMARY_USER')
if not PRIMARY_USER:
    raise ValueError("PRIMARY_USER must be set in .env file")
ADDITIONAL_USERS_STR = os.getenv('ADDITIONAL_USERS', '')
ADDITIONAL_USERS = [u.strip() for u in ADDITIONAL_USERS_STR.split(',') if u.strip()]
ALL_USERS = [PRIMARY_USER] + ADDITIONAL_USERS

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '_data'))
CACHE_DURATION = int(os.getenv('CACHE_DURATION', 3600))


@APP.template_filter('clean_url')
def clean_url_filter(endpoint, **kwargs):
    """Build path-based URLs like /genre/action/actor/Tom instead of ?genre=action&actor=Tom"""
    # Build path segments from parameters
    segments = []
    
    # Order matters for clean URLs - define the order we want
    param_order = ['view', 'user', 'genre', 'actor', 'search', 'media', 'period', 'year', 'rated', 'page', 'per_page']
    
    # Defaults to skip
    defaults = {
        'page': 1,
        'per_page': 10,
        'media': 'both',
        'period': 'all',
        'view': 'gallery',
        'user': PRIMARY_USER
    }

    # If a non-primary user is selected, prefix the URL with /<username>
    user_segment = None
    user_value = kwargs.get('user')
    if user_value and user_value != PRIMARY_USER:
        user_segment = quote(str(user_value), safe='')
    
    for param in param_order:
        if param not in kwargs:
            continue
        value = kwargs[param]
        # Skip empty, None, or default values
        if value is None or value == '' or (param in defaults and value == defaults[param]):
            continue
        # 'user' handled as leading segment
        if param == 'user':
            continue
        # URL encode the value and add as path segment: param/value
        encoded_value = quote(str(value), safe='')
        segments.append(f"{param}/{encoded_value}")
    
    if user_segment and segments:
        return '/' + user_segment + '/' + '/'.join(segments)
    if user_segment and not segments:
        return '/' + user_segment
    if segments:
        return '/' + '/'.join(segments)
    return '/'


APP.jinja_env.globals['clean_url'] = clean_url_filter


def get_user_data_path(username: str = None):
    """Get the data path for a given user. If username is None, uses primary user."""
    if username is None or username == PRIMARY_USER:
        # Primary user uses default path for backward compatibility
        return os.path.join(DATA_DIR, 'trakt_history.json')
    return os.path.join(DATA_DIR, f'trakt_history_{username}.json')


def get_user_raw_path(username: str = None):
    """Get the raw cache path for a given user."""
    if username is None or username == PRIMARY_USER:
        return os.path.join(DATA_DIR, 'trakt_raw.json')
    return os.path.join(DATA_DIR, f'trakt_raw_{username}.json')


def load_data(username: str = None):
    """Load history data for specified user (or primary user if None)."""
    data_path = get_user_data_path(username)
    if not os.path.exists(data_path):
        return {'generated_at': None, 'count': 0, 'items': []}
    with open(data_path, 'r') as f:
        return json.load(f)


@APP.route('/')
@APP.route('/<path:params>')
def index(params=None):
    # Parse path-based parameters like /genre/action/actor/Tom
    args = {}
    
    if params:
        parts = params.split('/')
        known_keys = {'view', 'user', 'genre', 'actor', 'search', 'media', 'period', 'year', 'rated', 'page', 'per_page'}

        # Support /<username> and /<username>/param/value
        if parts and parts[0] in ALL_USERS and parts[0] not in known_keys:
            args['user'] = parts[0]
            parts = parts[1:]

        # Parse pairs: param/value
        for i in range(0, len(parts) - 1, 2):
            if i + 1 < len(parts):
                key = parts[i]
                value = unquote(parts[i + 1])  # URL decode the value
                args[key] = value
    
    # Merge with query string args (fallback for old URLs)
    for key in request.args:
        if key not in args:
            args[key] = request.args.get(key)
    
    # Get selected user (default to primary user)
    selected_user = args.get('user', PRIMARY_USER)
    if selected_user not in ALL_USERS:
        selected_user = PRIMARY_USER
    
    data = load_data(selected_user)
    # pagination params
    try:
        page = max(1, int(args.get('page', 1)))
    except Exception:
        page = 1
    try:
        per_page = int(args.get('per_page', 10))
        if per_page <= 0:
            per_page = 10
    except Exception:
        per_page = 10

    # optional genre filter
    genre = args.get('genre')
    if genre:
        genre = genre.strip()

    # optional actor filter
    actor = args.get('actor')
    if actor:
        actor = actor.strip()

    # optional search filter
    search = args.get('search')
    if search:
        search = search.strip()

    # optional media filter: 'both' (default), 'movies', 'series'
    media = args.get('media', 'both') or 'both'
    media = media.strip().lower()
    if media not in ('both', 'movies', 'series'):
        media = 'both'

    # optional time-period filter: 'all', 'week', 'month', 'year'
    period = args.get('period', 'all') or 'all'
    period = period.strip().lower()
    if period not in ('all', 'week', 'month', 'year'):
        period = 'all'

    # optional release year filter
    release_year = args.get('year', '') or ''
    release_year = release_year.strip()

    # optional rated only filter
    rated_only = args.get('rated', '') or ''
    rated_only = rated_only.strip().lower()
    if rated_only not in ('yes', 'no', ''):
        rated_only = ''
    
    # optional view mode: 'gallery' (default) or 'calendar'
    view_mode = args.get('view', 'gallery') or 'gallery'
    view_mode = view_mode.strip().lower()
    if view_mode not in ('gallery', 'calendar'):
        view_mode = 'gallery'

    # Filter items by genre when requested (case-insensitive match)
    items_all = data.get('items', [])
    if genre:
        def _match_genre(item):
            gs = item.get('genres') or []
            try:
                return any(g.lower() == genre.lower() for g in gs)
            except Exception:
                return False
        items_all = [it for it in items_all if _match_genre(it)]

    # Filter by actor when requested (case-insensitive match)
    if actor:
        def _match_actor(item):
            cast = item.get('cast') or []
            try:
                return any(a.lower() == actor.lower() for a in cast)
            except Exception:
                return False
        items_all = [it for it in items_all if _match_actor(it)]

    # Filter by search query (searches title, actors, and year)
    if search:
        def _match_search(item):
            search_lower = search.lower()
            # Search in title
            title = item.get('title', '').lower()
            if search_lower in title:
                return True
            # Search in show title (for episodes)
            if item.get('type') == 'episode' and item.get('show'):
                show_title = item.get('show', {}).get('title', '').lower()
                if search_lower in show_title:
                    return True
            # Search in actors
            cast = item.get('cast') or []
            for actor_name in cast:
                if search_lower in actor_name.lower():
                    return True
            # Search by year (exact match)
            year = item.get('year')
            if year and str(year) == search:
                return True
            return False
        items_all = [it for it in items_all if _match_search(it)]

    # Filter by media type when requested
    if media == 'movies':
        items_all = [it for it in items_all if (it.get('type') == 'movie')]
    elif media == 'series':
        # 'series' here means episode entries
        items_all = [it for it in items_all if (it.get('type') == 'episode')]

    # Filter by time period when requested
    if period != 'all':
        now = datetime.now()
        
        def _parse_watched(item):
            watched = item.get('watched_at')
            if not watched:
                return None
            try:
                # Parse YYYY-MM-DD HH:MM format
                return datetime.strptime(watched, '%Y-%m-%d %H:%M')
            except Exception:
                return None
        
        if period == 'week':
            # Current week (Monday to Sunday)
            start_of_week = now - timedelta(days=now.weekday())
            start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            items_all = [it for it in items_all if _parse_watched(it) and _parse_watched(it) >= start_of_week]
        elif period == 'month':
            # Current month
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            items_all = [it for it in items_all if _parse_watched(it) and _parse_watched(it) >= start_of_month]
        elif period == 'year':
            # Current year
            start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            items_all = [it for it in items_all if _parse_watched(it) and _parse_watched(it) >= start_of_year]

    # Filter by release year when requested
    if release_year:
        try:
            year_int = int(release_year)
            items_all = [it for it in items_all if it.get('year') == year_int]
        except ValueError:
            pass  # ignore invalid year input

    # Filter by rated only when requested
    if rated_only == 'yes':
        items_all = [it for it in items_all if it.get('rating') is not None]

    total = len(items_all)
    total_pages = max(1, ceil(total / per_page))
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page
    items = items_all[start:end]

    # Format generated_at to human-readable format
    def _format_generated_at(s):
        if not s:
            return None
        try:
            # Handle ISO format with Z or timezone
            if isinstance(s, str):
                # Replace Z with +00:00 for Python's fromisoformat
                s = s.replace('Z', '+00:00')
                # Handle fractional seconds if present
                if '.' in s and '+' in s:
                    # Split on + to separate datetime from timezone
                    dt_part, tz_part = s.rsplit('+', 1)
                    # Limit fractional seconds to 6 digits
                    if '.' in dt_part:
                        base, frac = dt_part.split('.')
                        frac = frac[:6]
                        s = f"{base}.{frac}+{tz_part}"
                dt = datetime.fromisoformat(s)
            else:
                dt = s
            # Convert to local timezone
            local_dt = dt.astimezone()
            return local_dt.strftime('%B %d, %Y at %I:%M %p')
        except Exception:
            return s

    # For calendar mode, group items by date and paginate by date
    calendar_items = None
    if view_mode == 'calendar':
        from collections import defaultdict
        calendar_items_dict = defaultdict(list)
        for it in items_all:
            watched_date = (it.get('watched_at') or '').split(' ')[0] if it.get('watched_at') else 'Unknown'
            calendar_items_dict[watched_date].append(it)
        # Sort dates in reverse (most recent first)
        sorted_dates = sorted(calendar_items_dict.keys(), reverse=True)
        
        # Paginate by date
        total = len(sorted_dates)
        total_pages = max(1, ceil(total / per_page))
        if page > total_pages:
            page = total_pages
        start = (page - 1) * per_page
        end = start + per_page
        paginated_dates = sorted_dates[start:end]
        
        calendar_items = {date: calendar_items_dict[date] for date in paginated_dates}
    
    paged = {
        'generated_at': _format_generated_at(data.get('generated_at')),
        'generation_time': data.get('generation_time'),
        'count': total,
        'items': items,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'filter_genre': genre,
        'filter_actor': actor,
        'filter_search': search,
        'filter_media': media,
        'filter_period': period,
        'filter_year': release_year,
        'filter_rated': rated_only,
        'view_mode': view_mode,
        'calendar_items': calendar_items,
    }

    per_page_options = [10, 25, 50, 100]
    
    # Get unique years from all items for the year dropdown
    all_years = set()
    for it in data.get('items', []):
        if it.get('year'):
            all_years.add(it.get('year'))
    available_years = sorted(all_years, reverse=True)
    
    # Calculate statistics from all items (unfiltered)
    all_items = data.get('items', [])
    stats = {}
    
    # Total watch time (sum of all runtimes)
    total_runtime = sum(it.get('runtime', 0) or 0 for it in all_items)
    stats['total_hours'] = round(total_runtime / 60, 1) if total_runtime else 0
    stats['total_days'] = round(total_runtime / 60 / 24, 1) if total_runtime else 0
    
    # Count movies vs episodes
    stats['total_movies'] = sum(1 for it in all_items if it.get('type') == 'movie')
    stats['total_episodes'] = sum(1 for it in all_items if it.get('type') == 'episode')
    
    # Most watched actor (from cast arrays)
    from collections import Counter
    actor_counter = Counter()
    for it in all_items:
        cast = it.get('cast', [])
        if isinstance(cast, list):
            for actor in cast:
                if actor:
                    actor_counter[actor] += 1
    stats['top_actor'] = actor_counter.most_common(1)[0] if actor_counter else None
    
    # Most watched genre
    genre_counter = Counter()
    for it in all_items:
        genres = it.get('genres', [])
        if isinstance(genres, list):
            for genre in genres:
                if genre:
                    genre_counter[genre] += 1
    stats['top_genre'] = genre_counter.most_common(1)[0] if genre_counter else None
    
    # Year with most watches (release year, not watch year)
    year_counter = Counter()
    for it in all_items:
        year = it.get('year')
        if year:
            year_counter[year] += 1
    stats['top_year'] = year_counter.most_common(1)[0] if year_counter else None
    
    # Average rating
    ratings = [it.get('rating') for it in all_items if it.get('rating') is not None]
    stats['avg_rating'] = round(sum(ratings) / len(ratings), 1) if ratings else None
    stats['rated_count'] = len(ratings)

    ratings_note = None
    if selected_user != PRIMARY_USER:
        ratings_note = f"Ratings are only available for primary user ({PRIMARY_USER})."
    
    return render_template('index.html', data=paged, per_page_options=per_page_options, available_years=available_years, stats=stats,
                           all_users=ALL_USERS, selected_user=selected_user, primary_user=PRIMARY_USER, ratings_note=ratings_note, view_mode=view_mode)


@APP.route('/api/history')
def api_history():
    selected_user = request.args.get('user', PRIMARY_USER)
    if selected_user not in ALL_USERS:
        selected_user = PRIMARY_USER
    data = load_data(selected_user)
    return jsonify(data)


@APP.route('/raw')
def raw():
    """Return the raw cached Trakt response (first item) for debugging."""
    selected_user = request.args.get('user', PRIMARY_USER)
    if selected_user not in ALL_USERS:
        selected_user = PRIMARY_USER
    raw_path = get_user_raw_path(selected_user)
    if not os.path.exists(raw_path):
        return jsonify({'error': 'raw cache not found', 'path': raw_path}), 404
    try:
        with open(raw_path, 'r') as f:
            raw = json.load(f)
        # return first item and total count for quick inspection
        return jsonify({'count': len(raw), 'first': raw[0] if raw else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@APP.route('/refresh')
def refresh():
    # Get selected user (default to primary user)
    selected_user = request.args.get('user', PRIMARY_USER)
    if selected_user not in ALL_USERS:
        selected_user = PRIMARY_USER
    
    # Prefer running the centralized updater script to ensure consistent
    # season-resolution and normalization. This keeps resolver logic in one place.
    updater = os.path.join(os.path.dirname(__file__), 'scripts', 'update_trakt_local.py')
    if not os.path.exists(updater):
        flash('Updater script not found: scripts/update_trakt_local.py', 'error')
        return redirect(url_for('index', user=selected_user))

    # Check data freshness
    data_path = get_user_data_path(selected_user)
    try:
        if os.path.exists(data_path):
            mtime = os.path.getmtime(data_path)
            age = time.time() - mtime
            if age < CACHE_DURATION:
                flash(f'Data is fresh (updated {int(age)}s ago). Skipping refresh.', 'success')
                return redirect(url_for('index', user=selected_user))

        # Run the updater for this user with --no-cast and --no-enrichment for faster web refreshes
        # Cast fetching and show enrichment require many API calls and can take 5-10+ minutes
        # Users can run manually with full data: python3 scripts/update_trakt_local.py --user <username>
        # Increase timeout to 15 minutes for very slow connections
        venv_python = os.path.join(os.path.dirname(__file__), '.venv', 'bin', 'python')
        python_exec = sys.executable
        if not python_exec or not os.path.exists(python_exec):
            python_exec = venv_python if os.path.exists(venv_python) else 'python3'
        cmd = [python_exec, updater, '--user', selected_user]
        # Incremental updates are fast and ratings are always fetched fresh on every run
        proc = subprocess.run(
            cmd,
            cwd=os.path.dirname(__file__), 
            capture_output=True, 
            text=True, 
            timeout=900
        )
        if proc.returncode == 0:
            flash(f'Refresh completed successfully for {selected_user}', 'success')
        else:
            msg = proc.stderr.strip() or proc.stdout.strip() or f'return code {proc.returncode}'
            flash(f'Refresh failed: {msg[:1000]}', 'error')
    except subprocess.TimeoutExpired:
        flash('Refresh timed out after 15 minutes. Try running manually: python3 scripts/update_trakt_local.py --user <username>', 'error')
    except Exception as e:
        flash(f'Failed to run updater: {e}', 'error')

    return redirect(url_for('index', user=selected_user))


if __name__ == '__main__':
    # Start background scheduler for automatic updates
    if HAS_SCHEDULER:
        start_scheduler()
    
    try:
        APP.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=os.getenv('FLASK_DEBUG', '1') == '1')
    finally:
        if HAS_SCHEDULER:
            stop_scheduler()
