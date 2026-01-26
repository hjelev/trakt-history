# Trakt Flask Viewer

A minimal Flask app to view your Trakt watch history locally.

Requirements
- Python 3.8+
- `requests` and `python-dotenv` (install with `pip install -r requirements.txt`)

Setup
1. Copy the example env and fill values:
Optional: enable RatingPosterDB thumbnails
-------------------------------------------------
If you have an RPDB API key (from https://ratingposterdb.com/), add it to your `.env`:

```bash
# in the trakt/ folder
echo "RPDB_API_KEY=t0-free-rpdb" >> .env
# or edit trakt/.env and set RPDB_API_KEY=<your_key>
```

Then run the updater to populate thumbnails:

```bash
cd trakt
python3 scripts/update_trakt_local.py
```


```bash
cp trakt/.env.example trakt/.env
# edit trakt/.env and add TRAKT_REFRESH_TOKEN if you have it
```

2. (Optional) If you want to use the `/refresh` route to fetch fresh data, add:

- `TRAKT_CLIENT_ID`
- `TRAKT_CLIENT_SECRET`
- `TRAKT_REFRESH_TOKEN`

3. Install deps and run locally:

```bash
python -m venv .venv
. .venv/bin/activate
pip install requests python-dotenv flask
python trakt/app.py
```

The app serves at `http://127.0.0.1:5000/`.

Notes
- The `/refresh` route runs `scripts/generate_trakt_data.py` and requires the refresh token flow variables.
- The generator writes `_data/trakt_history.json` which the Flask app reads to show the history.
