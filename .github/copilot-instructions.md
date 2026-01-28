# Trakt Watch History Viewer - AI Agent Instructions

## Project Overview

A Flask web application that displays, filters, and analyzes Trakt.tv watch history locally. Users authenticate with Trakt via OAuth, fetch their watch history (movies & TV episodes), enrich it with metadata (cast, genres, posters), and browse through a responsive Bootstrap 5 UI.

## Architecture

### Core Components

1. **[app.py](app.py)** - Flask web server
   - HTTP routes for UI, filtering, search, pagination
   - Data filtering logic (genre, actor, media type, time period, release year, ratings)
   - Loads processed JSON from `_data/trakt_history.json`

2. **[main.py](main.py)** - Trakt API wrapper
   - Handles OAuth token persistence in `trakt.json`
   - Minimal wrapper around `trakt.py` library (imported by update script)
   - No direct HTTP calls; uses trakt.py package for API access

3. **[authenticate.py](authenticate.py)** - One-time OAuth setup
   - Device authentication flow (user visits URL, enters code)
   - Saves token to `trakt.json` for reuse
   - Run once before fetching history

4. **[scripts/update_trakt_local.py](scripts/update_trakt_local.py)** - Data pipeline
   - ~1000 lines: fetches history, enriches with metadata, generates UI-ready JSON
   - CLI flags: `--no-cast`, `--no-enrichment`, `--no-images`, `--limit`, `--force`
   - Imports `main.py` to access authenticated Trakt client
   - Outputs to `_data/trakt_history.json` (processed data) and `_data/trakt_raw.json` (raw API dump)
   - Caches raw API data to avoid redundant fetches; skips reprocessing if raw data unchanged

5. **[templates/index.html](templates/index.html)** - Bootstrap 5 UI
   - Responsive card grid with poster thumbnails, ratings overlay
   - Dark mode auto-detect (CSS media query)
   - Desktop: 240px cards; Mobile: 160px cards; <400px: 140px cards
   - Real-time client-side filtering via JavaScript

### Data Flow

```
Trakt.tv API → authenticate.py → trakt.json (OAuth token)
                     ↓
         main.py (authenticate()) + trakt.py library
                     ↓
    update_trakt_local.py (fetch + enrich)
                     ↓
    _data/trakt_raw.json (API response dump)
         ↓                     ↓
    Enrichment pipeline    Cache check
         ↓
    _data/trakt_history.json (UI-ready JSON)
         ↓
    app.py (server-side filtering + app.js (client-side))
         ↓
    index.html (Bootstrap UI)
```

## Key Patterns & Conventions

### Data Structure
- Each item in `trakt_history.json['items']` has: `type` ('movie' or 'episode'), `title`, `year`, `watched_at`, `genres` (list), `cast` (list), `rating` (user's rating or null), `poster_url`, `show` (for episodes with title/year), `ids`
- Time format: `'%Y-%m-%d %H:%M'` (e.g., `'2025-01-28 14:30'`)
- Genres/cast are lowercase-normalized for case-insensitive filtering

### Environment Configuration
- `.env` file (not git-tracked) contains: `TRAKT_CLIENT_ID`, `TRAKT_CLIENT_SECRET`, `PRIMARY_USER`, `ADDITIONAL_USERS` (comma-separated), `FLASK_SECRET`, `CACHE_DURATION` (seconds), `PORT`, `FLASK_DEBUG`
- `PRIMARY_USER` (REQUIRED) - your account username, used by default for CLI refreshes
- `ADDITIONAL_USERS` - comma-separated usernames of other users (e.g., `petrovgeorgi6,friend1`) - each gets separate cache files
- Single token file: `trakt.json` - your authentication used to fetch all users' public watch history
- Example: see `.env.example` and `trakt-app.service.example`

### Update/Refresh Workflow
```bash
# Initial setup (one-time authentication)
python authenticate.py                                    # One-time OAuth (creates trakt.json)
python scripts/update_trakt_local.py                      # Fetch & process for primary user (default)
python scripts/update_trakt_local.py --user petrovgeorgi6 # Fetch public history for additional user

# Routine updates (respects cache)
python scripts/update_trakt_local.py                      # Updates primary user only
python scripts/update_trakt_local.py --user petrovgeorgi6 # Updates specific user

# Debug/troubleshooting (skip expensive operations)
python scripts/update_trakt_local.py --no-cast --no-enrichment --no-images
python scripts/update_trakt_local.py --user petrovgeorgi6 --limit 50 --verbose
python scripts/update_trakt_local.py --user petrovgeorgi6 --force  # Ignore cache, reprocess raw data

# Web UI refresh (per-user, respects cache)
# Click "🔄 Refresh" button next to user selector
# Or visit /refresh?user=petrovgeorgi6 to refresh specific user
```

### Deployment
- Systemd service: `trakt-app.service` (for Pi or Linux servers)
- Points to `.venv/bin/python` and `app.py`
- User runs `python app.py` locally (Flask debug mode)

## Development Workflows

### Running Locally
```bash
source .venv/bin/activate
python app.py              # Starts Flask on http://localhost:5000
```

### Updating Watch History
- Run `scripts/update_trakt_local.py` independently of Flask server
- Script validates/creates `_data/` directory automatically
- Always loads Trakt credentials from `.env` before executing

### Debugging
- `app.py` routes print filter debug info to console
- Update script has `--verbose` flag for detailed enrichment logging
- Check `update.log` and `update_force.log` for historical run output

## Important Implementation Details

- **Token management**: `main.py` checks `trakt.json` exists and is valid JSON before using; `trakt.py` lib handles OAuth refresh internally
- **Pagination**: Server-side query string (`?page=X&per_page=Y`); defaults to page 1, 10 items
- **Search**: Case-insensitive substring match across title, show title (for episodes), cast, and exact year match
- **Filtering stacking**: genre → actor → search → media type → time period → release year (applied sequentially on items_all)
- **Episodes**: Stored as separate items with `type='episode'`, `show={'title': '...', 'year': ...}`, and enriched with show-level genres/year
- **Caching strategy**: Raw API data cached in `trakt_raw.json`; update script checks if contents changed before re-enriching (avoid re-fetching posters/cast if unnecessary)

## Common Tasks

### Add a new filter to the UI
1. Add query param handling in `app.py` index() (e.g., `request.args.get('new_filter')`)
2. Apply filter logic to `items_all` list
3. Add dropdown/input to `index.html` form
4. Ensure filter param is preserved in pagination links

### Modify data enrichment
1. Edit `scripts/update_trakt_local.py` enrichment section
2. Understand the raw API structure (check `_data/trakt_raw.json` for examples)
3. Test with `--limit 10 --verbose` before full run
4. Use `--force` to reprocess without re-fetching

### Change UI styling
- Edit `<style>` block in `index.html`
- Responsive breakpoints: 720px (tablet), 400px (small mobile)
- Dark mode CSS: `@media (prefers-color-scheme: dark)` section
