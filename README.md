# 🎬 Trakt Watch History Viewer

<div align="center">

A modern Flask web application to view, search, and analyze your Trakt.tv watch history locally with powerful filtering, personal ratings, and beautiful poster thumbnails.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.0+-green.svg)](https://flask.palletsprojects.com/)
[![Bootstrap 5](https://img.shields.io/badge/bootstrap-5.3-purple.svg)](https://getbootstrap.com/)

</div>

## ✨ Features

- 📺 **Complete Watch History** - View all your movies & TV episodes from Trakt.tv
- 🎯 **Advanced Filtering** - Filter by genre, actor, media type, time period, and release year
- 🔍 **Smart Search** - Search across titles, actors, and years instantly
- ⭐ **Personal Ratings** - Display your ratings from Trakt on each poster
- 🖼️ **Beautiful Posters** - High-quality poster thumbnails from RatingPosterDB
- 📊 **Statistics** - Watch analytics and insights
- 🎨 **Modern UI** - Responsive Bootstrap 5 interface with card-based layout
- ⚡ **Fast Performance** - Local caching with smart update strategies

## 📋 Requirements

- Python 3.8 or higher
- Trakt.tv account (free)
- Trakt API credentials ([get them here](https://trakt.tv/oauth/applications))
- (Optional) RatingPosterDB API key for poster thumbnails

## 🚀 Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/trakt-history.git
cd trakt-history

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Trakt API

**Get your API credentials:**
1. Visit [Trakt API Applications](https://trakt.tv/oauth/applications)
2. Click "New Application"
3. Fill in the form:
   - **Name**: My Trakt History Viewer
   - **Redirect URI**: `urn:ietf:wg:oauth:2.0:oob`
4. Click "Save App"
5. Copy your **Client ID** and **Client Secret**

**Configure environment:**

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your favorite editor
nano .env  # or vim, code, etc.
```

Add your credentials to `.env`:

```bash
TRAKT_CLIENT_ID=your_client_id_here
TRAKT_CLIENT_SECRET=your_client_secret_here
FLASK_SECRET=your_random_secret_key_here
CACHE_DURATION=3600
PORT=5000
FLASK_DEBUG=1

# Optional: RatingPosterDB API key for poster thumbnails
RPDB_API_KEY=your_rpdb_key_here  # Get from https://ratingposterdb.com/
```

### 3. Authenticate with Trakt

```bash
python authenticate.py
```

This will:
1. Open your browser to Trakt's authorization page
2. Display a code to enter on the Trakt website
3. Wait for your authorization
4. Save your access token to `trakt.json`

### 4. Fetch Your Watch History

```bash
# Fast update (recommended for first run)
python scripts/update_trakt_local.py --no-cast --no-enrichment

# Or with poster thumbnails (if you have RPDB API key)
python scripts/update_trakt_local.py --no-cast --no-enrichment
```

This will download your complete watch history and generate the local database.

### 5. Run the Application

```bash
python app.py
```

Visit **http://localhost:5000** in your browser! 🎉

## 📱 Usage

### Update Your Watch History

The app provides multiple ways to update your data:

**Option 1: Web Interface (Fastest)**
- Visit `http://localhost:5000/refresh` in your browser
- Uses quick update mode (`--no-cast --no-enrichment`)
- Takes ~30-60 seconds (fast machines) or ~1-2 minutes (Raspberry Pi)

**Option 2: Command Line**

```bash
# Fastest: Quick update without cast/enrichment
python scripts/update_trakt_local.py --no-cast --no-enrichment

# Faster: With show enrichment (genres, year) but no cast
python scripts/update_trakt_local.py --no-cast

# Full: Complete data with cast and enrichment (5-10 minutes)
python scripts/update_trakt_local.py

# Force refresh: Reprocess all data even if unchanged
python scripts/update_trakt_local.py --force

# Skip images: Don't download poster thumbnails
python scripts/update_trakt_local.py --no-images

# Limit items: Process only first N items (for testing)
python scripts/update_trakt_local.py --limit 50
```

**Performance Guide:**
| Mode | Time (Intel/AMD) | Time (Raspberry Pi) | API Calls |
|------|------------------|---------------------|-----------|
| `--no-cast --no-enrichment` | 30-60s | 1-2 min | ~3-5 |
| `--no-cast` | 2-3 min | 3-5 min | ~15-20 |
| Full mode | 5-10 min | 10-15 min | ~100+ |

### Browse Your History

Navigate to `http://localhost:5000` to explore your watch history with:
- **Filters**: Genre, actor, year, media type, time period
- **Search**: Find content by title, actor, or year
- **Sorting**: Sort by watch date, title, or rating
- **Pagination**: Navigate through your complete history

## 🖥️ Running as a Service (Linux)

To run the app automatically on system startup:

### 1. Copy and Configure Service File

```bash
# Copy the example service file
cp trakt-app.service.example trakt-app.service

# Edit with your username and paths
nano trakt-app.service
```

Update these values in the service file:
- Replace `username` with your actual username
- Update paths to match your installation directory

Example for user `john` with app in `/home/john/trakt-history`:
```ini
[Service]
User=john
WorkingDirectory=/home/john/trakt-history
Environment="PATH=/home/john/trakt-history/.venv/bin"
ExecStart=/home/john/trakt-history/.venv/bin/python /home/john/trakt-history/app.py
```

### 2. Install and Enable Service

```bash
# Copy service file to systemd
sudo cp trakt-app.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable trakt-app.service

# Start the service now
sudo systemctl start trakt-app.service

# Check status
sudo systemctl status trakt-app.service
```

### 3. Service Management

```bash
# View logs
sudo journalctl -u trakt-app.service -f

# Restart service
sudo systemctl restart trakt-app.service

# Stop service
sudo systemctl stop trakt-app.service

# Disable service
sudo systemctl disable trakt-app.service
```

## 📁 Project Structure

```
trakt-history/
├── app.py                          # Main Flask application
├── authenticate.py                 # Trakt OAuth authentication script
├── main.py                         # Trakt API wrapper module
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variables template
├── .env                            # Your environment config (not in git)
├── trakt.json                      # OAuth token (generated, not in git)
├── trakt-app.service.example       # systemd service template
├── templates/
│   └── index.html                  # Main web interface
├── scripts/
│   └── update_trakt_local.py       # Data fetcher and processor
└── _data/                          # Generated data (not in git)
    ├── trakt_history.json          # Processed watch history
    └── trakt_raw.json              # Raw API response cache
```

## 🛠️ API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main web interface |
| `/api/history` | GET | JSON API with filtering/pagination |
| `/refresh` | GET | Trigger data update from Trakt |
| `/raw` | GET | View raw cached data (debugging) |

**Query Parameters for `/api/history`:**
- `page` - Page number (default: 1)
- `per_page` - Items per page (default: 20)
- `search` - Search query
- `genre` - Filter by genre
- `actor` - Filter by actor name
- `type` - Filter by media type (movie/episode)
- `period` - Time period filter
- `year` - Release year filter

## 🔧 Configuration Options

Edit `.env` to customize behavior:

```bash
# Trakt API (required)
TRAKT_CLIENT_ID=your_client_id
TRAKT_CLIENT_SECRET=your_client_secret

# Flask app (required)
FLASK_SECRET=random_secret_key_here
PORT=5000                    # Web server port
FLASK_DEBUG=1                # Enable debug mode (0 for production)

# Caching
CACHE_DURATION=3600          # Cache duration in seconds (1 hour)

# RatingPosterDB (optional)
RPDB_API_KEY=your_key        # For poster thumbnails
```

## 🎨 Features in Detail

### Personal Ratings
Your personal ratings from Trakt.tv are displayed on each poster with a ⭐ badge in the top-right corner. Only items you've rated will show the badge.

### Poster Thumbnails
High-quality poster images are loaded directly from RatingPosterDB CDN when you provide an API key. The app generates optimized image URLs for fast loading without local storage.

### Smart Caching
- Raw API responses cached for 1 hour (configurable)
- Processed data stored locally in JSON format
- Poster URLs generated once and cached in data
- Fast subsequent loads

### Responsive Design
Bootstrap 5 provides a modern, mobile-friendly interface that adapts to any screen size.

## 🐛 Troubleshooting

**Authentication fails:**
- Verify your Client ID and Secret in `.env`
- Make sure redirect URI is set to `urn:ietf:wg:oauth:2.0:oob`
- Delete `trakt.json` and re-run `python authenticate.py`

**No posters showing:**
- Check if you have RPDB_API_KEY in `.env`
- Run update script without `--no-images` flag
- Verify your RPDB API key is valid at https://ratingposterdb.com/

**Service won't start:**
- Check service status: `sudo systemctl status trakt-app.service`
- View logs: `sudo journalctl -u trakt-app.service -n 50`
- Verify paths in service file match your installation
- Ensure virtual environment is activated when testing manually

**Slow updates:**
- Use `--no-cast --no-enrichment` for fastest updates
- Enable caching (default)
- Consider running full updates less frequently

## 📝 Notes

- Data is fetched fresh on `/refresh` and cached locally
- The `_data/` directory is excluded from git (contains your personal data)
- First update takes longer to download all watch history
- Subsequent updates only fetch new items
- Use `--force` flag to reprocess all data

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- [Trakt.tv](https://trakt.tv) - Watch history tracking
- [RatingPosterDB](https://ratingposterdb.com) - High-quality poster images
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [Bootstrap 5](https://getbootstrap.com/) - UI framework
