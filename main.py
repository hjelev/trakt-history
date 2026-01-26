import os
import json
from datetime import datetime
from dotenv import load_dotenv
from trakt import Trakt
from trakt.objects import Movie, Episode
from dateutil.relativedelta import relativedelta
import time
import pickle # Using pickle to save the actual Trakt objects

CACHE_FILE = "trakt_cache.pkl"
CACHE_DURATION = 3600 # 1 hour in seconds

load_dotenv()

# File where the token will be stored
TOKEN_FILE = 'trakt.json'
CLIENT_ID = os.getenv('TRAKT_CLIENT_ID')
CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET')

def get_cached_history():
    # Check if cache exists and is fresh
    if os.path.exists(CACHE_FILE):
        file_age = time.time() - os.path.getmtime(CACHE_FILE)
        if file_age < CACHE_DURATION:
            print(f"--- Loading from JSON cache ({int(file_age/60)}m old) ---")
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)

    print("--- Cache expired or missing. Hitting Trakt API... ---")
    try:
        history = Trakt['sync/history'].get(pagination=True, per_page=100, extended='full')
        
        # Convert complex objects to simple dictionaries for JSON
        serialized_data = []
        for item in history:
            # We use to_dict() and manually add the class name for logic later
            data = item.to_dict()
            data['class_name'] = type(item).__name__
            # Convert datetime to string for JSON
            if item.watched_at:
                data['watched_at_str'] = item.watched_at.isoformat()
            serialized_data.append(data)

        with open(CACHE_FILE, 'w') as f:
            json.dump(serialized_data, f)
            
        return serialized_data
    except Exception as e:
        print(f"API Error: {e}")
        return None
    
def calculate_history_span(first_watch, last_watch):
    """Calculates the time difference between the first and last watch dates."""
    if not (first_watch and last_watch):
        return "N/A"
    
    # Ensure we are comparing the right directions (earliest vs latest)
    start = min(first_watch, last_watch)
    end = max(first_watch, last_watch)
    
    diff = relativedelta(end, start)
    
    parts = []
    if diff.years > 0:
        parts.append(f"{diff.years} year{'s' if diff.years != 1 else ''}")
    if diff.months > 0:
        parts.append(f"{diff.months} month{'s' if diff.months != 1 else ''}")
    if diff.days > 0:
        parts.append(f"{diff.days} day{'s' if diff.days != 1 else ''}")
    
    return ", ".join(parts) if parts else "Same day"


def authenticate():
    Trakt.configuration.defaults.client(id=CLIENT_ID, secret=CLIENT_SECRET)
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)
            Trakt.configuration.defaults.oauth.from_response(token_data)
            return True
    return False

def calculate_age(watched_iso, rel_date_str):
    if not watched_iso or not rel_date_str: return "n/a"
    try:
        w_date = datetime.fromisoformat(watched_iso.split('T')[0]).date()
        r_date = datetime.strptime(rel_date_str[:10], "%Y-%m-%d").date()
        diff = (w_date - r_date).days
        if diff < 0: return "Pre-rel"
        if diff < 31: return f"{diff}d"
        if diff < 365: return f"{diff // 30}m"
        return f"{diff // 365}y"
    except: return "n/a"

def get_history_span_str(earliest, latest):
    if not earliest or not latest: return "n/a"
    diff = relativedelta(latest, earliest)
    parts = []
    if diff.years: parts.append(f"{diff.years}y")
    if diff.months: parts.append(f"{diff.months}m")
    if diff.days: parts.append(f"{diff.days}d")
    return " ".join(parts) if parts else "0d"

def format_title_dict(item):
    is_movie = item.get('class_name') == 'Movie'
    if is_movie:
        return f"{item.get('title')} ({item.get('year', '????')})"
    
    # Episode logic
    show_name = item.get('show', {}).get('title', 'Unknown Show')
    s = item.get('season', '?')
    e = item.get('number', '?')
    return f"{show_name} S{s}E{e}"

def get_imdb_url(item):
    """Extracts the IMDb URL from the item's ID dictionary."""
    ids = item.to_dict().get('ids', {})
    imdb_id = ids.get('imdb')
    return f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "N/A"

def format_title(item, is_movie):
    """Handles the naming and S/E numbering for movies vs episodes."""
    if is_movie:
        year = getattr(item, 'year', None)
        return f"{item.title} ({year})" if year else item.title
    
    show_name = item.show.title if hasattr(item, 'show') else "Unknown"
    s_num = getattr(item, 'season', None)
    e_num = getattr(item, 'number', None)
    
    if s_num is not None and e_num is not None:
        return f"{show_name} S{s_num}E{e_num}"
    return f"{show_name} - {getattr(item, 'title', 'Ep')}"

from collections import Counter

def find_key(data, key_name):
    """Deeply searches for a key in a nested dictionary."""
    if key_name in data: return data[key_name]
    for k, v in data.items():
        if isinstance(v, dict):
            found = find_key(v, key_name)
            if found: return found
    return None

def display_history():
    history_data = None

    if os.path.exists(CACHE_FILE):
        file_age = time.time() - os.path.getmtime(CACHE_FILE)
        if file_age < CACHE_DURATION:
            with open(CACHE_FILE, 'r') as f:
                history_data = json.load(f)
                print(f"--- Loading from cache ({int(file_age/60)}m old) ---")

    if not history_data:
        print("--- Refreshing from Trakt API... ---")
        try:
            history = Trakt['sync/history'].get(pagination=True, per_page=100, extended='full')
            history_data = []
            for item in history:
                d = item.to_dict()
                d['force_type'] = 'movie' if type(item).__name__ == 'Movie' else 'episode'
                d['watched_at_iso'] = item.watched_at.isoformat() if item.watched_at else None
                
                if d['force_type'] == 'episode':
                    d['extracted_show_title'] = item.show.title if hasattr(item, 'show') else "Unknown Show"
                    if hasattr(item, 'episode'):
                        d['extracted_season'] = item.episode.season
                
                history_data.append(d)
            
            with open(CACHE_FILE, 'w') as f:
                json.dump(history_data, f, indent=4)
        except Exception as e:
            print(f"API Error: {e}"); return

    header = (f"{'TYPE':<8} | {'TITLE':<30} | {'WATCHED':<12} | "
              f"{'AGE':<11} | {'RT':<4} | {'SCORE':<6} | {'GENRES':<25} | {'IMDb LINK'}")
    print(f"\n{header}\n{'-' * 165}")

    total_minutes, seen_ids, watch_dates = 0, set(), []

    for item in history_data:
        # --- DEDUPLICATION FIX ---
        # Using ONLY the Trakt ID as the key removes duplicates
        t_id = item.get('ids', {}).get('trakt') or item.get('episode', {}).get('ids', {}).get('trakt')
        if not t_id or t_id in seen_ids: 
            continue
        seen_ids.add(t_id)

        is_movie = item.get('force_type') == 'movie'
        class_label = "MOVIE" if is_movie else "EPISODE"
        
        if is_movie:
            display_title = f"{item.get('title', 'Unknown')} ({item.get('year', '????')})"
        else:
            show_name = item.get('extracted_show_title') or "TV Show"
            s = item.get('extracted_season') or item.get('season') or "1"
            e = item.get('number') or "?"
            display_title = f"{show_name} S{s}E{e}"

        # Metadata
        rt = item.get('runtime', 0) or 0
        total_minutes += rt
        
        # Pull genres from show if it's an episode
        genres = item.get('genres') or item.get('show', {}).get('genres') or []
        genre_str = ", ".join(genres[:2]) if genres else "n/a"

        imdb_id = item.get('ids', {}).get('imdb') or item.get('episode', {}).get('ids', {}).get('imdb')
        imdb_url = f"https://www.imdb.com/title/{imdb_id}/"
        
        watched_iso = item.get('watched_at_iso')
        watched_dt = datetime.fromisoformat(watched_iso.replace('Z', '+00:00')) if watched_iso else None
        if watched_dt: watch_dates.append(watched_dt)
        w_str = watched_dt.strftime("%Y-%m-%d") if watched_dt else "Unknown"
        
        rel_date = item.get('released') or item.get('first_aired') or item.get('episode', {}).get('first_aired')
        age_info = calculate_age(watched_iso, rel_date)
        score_str = f"{round(float(item.get('rating', 0)), 1)}"

        print(f"{class_label:<8} | {display_title[:30]:<30} | {w_str:<12} | "
              f"{age_info:<11} | {rt:<4} | {score_str:<6} | {genre_str:<26} | {imdb_url}")

    if watch_dates:
        h, m = divmod(total_minutes, 60)
        days_diff = (max(watch_dates).date() - min(watch_dates).date()).days or 1
        print(f"{'-' * 165}\nSUMMARY: {len(seen_ids)} items | Total: {h}h {m}m | AVG: ~{int(total_minutes/days_diff)}m/day")

if __name__ == "__main__":
    if authenticate():
        display_history()
