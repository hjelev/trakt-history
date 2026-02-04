# Scheduler Usage Guide

## How the Scheduler Works

The scheduler automatically updates your Trakt watch history every hour. It:

1. **Runs in the background** - daemon mode, doesn't block the Flask web app
2. **Updates all configured users** - PRIMARY_USER and any ADDITIONAL_USERS  
3. **Logs detailed information** - to `scheduler.log` for debugging
4. **Handles errors gracefully** - reports issues without crashing

## Running the Scheduler

### Option 1: With Flask Web App (Recommended)

When you run the Flask app, the scheduler starts automatically:

```bash
python app.py
```

The scheduler will run in the background and start your first update 1 hour after app startup.

Check the log:
```bash
tail -f scheduler.log
```

### Option 2: Standalone Scheduler

To run the scheduler independently (for debugging or manual testing):

```bash
python scheduler.py
```

Output will appear in both the console and in `scheduler.log`.

Press `Ctrl+C` to stop.

### Option 3: As a Systemd Service

If deployed on Linux, you can use the provided service file:

```bash
sudo systemctl start trakt-app
sudo systemctl status trakt-app

# Check logs
journalctl -u trakt-app -f
tail -f /path/to/trakt/scheduler.log
```

## Troubleshooting

### Check if Scheduler is Running

```bash
# In Python shell
from scheduler import start_scheduler
scheduler = start_scheduler()
print(scheduler.get_jobs())
```

### View Detailed Logs

```bash
# All logs
cat scheduler.log

# Last 50 lines
tail -50 scheduler.log

# Follow in real-time
tail -f scheduler.log

# Filter for errors only
grep ERROR scheduler.log

# Filter for a specific user
grep "masoko" scheduler.log
```

### Manual Updates

If you need to update immediately without waiting for the scheduler:

```bash
# Update primary user (with --force to refresh ratings)
python scripts/update_trakt_local.py --user masoko --force

# Update additional user (cached mode)
python scripts/update_trakt_local.py --user petrovgeorgi6

# Quick test with limited data
python scripts/update_trakt_local.py --user masoko --limit 5 --no-enrichment
```

### Common Issues

**Issue**: Scheduler doesn't seem to be running
- **Solution**: Check `scheduler.log` for error messages
- Run `python verify_scheduler.py` to diagnose

**Issue**: Updates failing
- **Check**: 
  - Is `.env` file configured correctly?
  - Does `trakt.json` contain valid authentication token?
  - Is the update script accessible? (`ls -la scripts/update_trakt_local.py`)

**Issue**: Updates taking too long
- **Note**: First run may take 5-15 minutes to fetch posters/cast
- **Subsequent runs**: Should be faster (respects cache)
- **Primary user**: Forced refresh every hour (for ratings)
- **Additional users**: Cached mode (faster, use `--force` to refresh)

## Configuration

The scheduler reads from `.env` file:

```env
PRIMARY_USER=masoko              # Your main Trakt account
ADDITIONAL_USERS=petrovgeorgi6  # Comma-separated list of other users
```

The scheduler updates:
- `_data/trakt_history.json` (primary user, default path)
- `_data/trakt_history_<user>.json` (additional users)
- `_data/trakt_raw.json` and `_data/trakt_raw_<user>.json` (raw API cache)

## Performance Notes

- **Schedule**: Every 1 hour
- **Primary user**: Always forced refresh (--force flag) to get latest ratings
- **Other users**: Cached mode (respects 1-hour cache to avoid redundant API calls)
- **Timeout**: 10 minutes per user
- **Logs**: DEBUG level logging to `scheduler.log`

## Integration with Web UI

The web UI includes a "🔄 Refresh" button to manually trigger updates for the selected user, with a cache duration check to avoid redundant refreshes.

For full details on data filtering and enrichment, see [ARCHITECTURE.md](ARCHITECTURE.md) or the copilot instructions.
