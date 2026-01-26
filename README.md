# Trakt History Viewer

A Flask web application to view and analyze your Trakt.tv watch history locally with filtering, pagination, and statistics.

## Features

- View your complete Trakt watch history (movies & TV episodes)
- Filter by genre, actor, media type, time period, and release year
- Search across titles, actors, and years
- Pagination support
- Watch statistics and analytics
- Optional RatingPosterDB thumbnail integration

## Requirements

- Python 3.8+
- Trakt.tv account
- Trakt API credentials (Client ID & Secret)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/trakt-history.git
cd trakt-history
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example environment file and add your Trakt API credentials:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```bash
TRAKT_CLIENT_ID=your_client_id_here
TRAKT_CLIENT_SECRET=your_client_secret_here
FLASK_SECRET=your_random_secret_key
CACHE_DURATION=3600
PORT=5000
FLASK_DEBUG=1
```

**Getting Trakt API Credentials:**
1. Go to https://trakt.tv/oauth/applications
2. Create a new application
3. Copy the Client ID and Client Secret to your `.env` file

### 5. (Optional) Enable RatingPosterDB thumbnails

If you have an RPDB API key from https://ratingposterdb.com/, add it to `.env`:

```bash
RPDB_API_KEY=your_rpdb_key_here
```

Then run the updater to fetch thumbnails:

```bash
python3 scripts/update_trakt_local.py
```

## Usage

### Run the application

```bash
python app.py
```

The application will be available at `http://localhost:5000`

### First-time authentication

Before running the app, you need to authenticate with Trakt:

```bash
python authenticate.py
```

This will:
1. Display a URL to visit in your browser
2. Show a code to enter on the Trakt website
3. Wait for you to authorize the app
4. Save your token to `trakt.json`

Once authenticated, you can run the app normally.

### Update your watch history

Visit `http://localhost:5000/refresh` to fetch the latest data from Trakt.

**Note:** Web refresh uses `--no-cast --no-enrichment` flags for speed (~30-60 seconds on fast machines, ~1-2 minutes on RPi5). 

To fetch full data including cast actors and show enrichment, run manually:

```bash
python scripts/update_trakt_local.py
```

**Speed options:**
- **Fastest** (web refresh, no cast, no enrichment): ~30-60 seconds (Intel/AMD), ~1-2 minutes (RPi5)
  ```bash
  python scripts/update_trakt_local.py --no-cast --no-enrichment
  ```
- **With enrichment** (show genres/year, no cast): ~2-3 minutes
  ```bash
  python scripts/update_trakt_local.py --no-cast
  ```
- **Full data** (with cast and enrichment, slow): ~5-10 minutes (many API calls)
  ```bash
  python scripts/update_trakt_local.py
  ```

## Project Structure

```
trakt-history/
├── app.py                      # Main Flask application
├── requirements.txt            # Python dependencies
├── .env                        # Environment variables (not in git)
├── .env.example               # Environment template
├── templates/                 # HTML templates
├── scripts/                   # Data update scripts
│   └── update_trakt_local.py
└── _data/                     # Generated data (not in git)
    ├── trakt_history.json
    └── trakt_raw.json
```

## API Routes

- `/` - Main history view
- `/api/history` - JSON API endpoint
- `/refresh` - Fetch fresh data from Trakt
- `/raw` - View raw cached data (debugging)

## Notes

- The `/refresh` route fetches fresh data from Trakt and caches it locally
- Data is cached for 1 hour by default (configurable via `CACHE_DURATION`)
- The `_data/` directory contains generated data and is excluded from git
