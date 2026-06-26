# Scheduler Usage Guide

## How the Scheduler Works

The scheduler automatically updates your Trakt watch history every hour. It:

1. **Runs as its own process** - `scheduler.py`, independent of the Flask web app
2. **Updates all configured users** - PRIMARY_USER and any ADDITIONAL_USERS  
3. **Logs detailed information** - to the systemd journal and `scheduler.log` for debugging
4. **Handles errors gracefully** - reports issues without crashing

> **Note:** The scheduler is **not** started by the Flask web app. Running `python app.py`
> only serves the web UI — you must run the scheduler separately (systemd service below).

## Running the Scheduler

### Option 1: As a Systemd Service (Recommended)

On Linux, run the scheduler as a dedicated systemd service so it survives reboots and restarts
on failure. See the **Automatic Hourly Updates (Scheduler Service)** section in
[README.md](README.md) for the full setup; in short:

```bash
cp trakt-scheduler.service.example trakt-scheduler.service
nano trakt-scheduler.service        # set User= and the /home/<user>/... paths

sudo cp trakt-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trakt-scheduler.service
sudo systemctl status trakt-scheduler.service

# Check logs
sudo journalctl -u trakt-scheduler.service -f
tail -f scheduler.log
```

### Option 2: Standalone Scheduler

To run the scheduler in the foreground (for debugging or manual testing):

```bash
python scheduler.py
```

Output will appear in both the console and in `scheduler.log`.

Press `Ctrl+C` to stop.

## Troubleshooting

### Check if Scheduler is Running

```bash
# Is the systemd service active?
sudo systemctl status trakt-scheduler.service

# Recent service output
sudo journalctl -u trakt-scheduler.service -n 50

# Diagnose configuration (imports, users, paths, log)
python verify_scheduler.py
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
- **Subsequent runs**: Should be faster (incremental, respects cache)
- **All users**: Incremental updates each hour; ratings are always fetched fresh
- **Manual full refresh**: run the update script with `--force` if needed

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
- **All users**: Incremental updates (no `--force`) to stay fast and avoid timeouts
- **Ratings**: Always fetched fresh on every run (the ratings API is fast)
- **Timeout**: 10 minutes per user
- **Logs**: DEBUG level logging to `scheduler.log`

## Integration with Web UI

The web UI includes a "🔄 Refresh" button to manually trigger updates for the selected user, with a cache duration check to avoid redundant refreshes.

For full details on data filtering and enrichment, see [ARCHITECTURE.md](ARCHITECTURE.md) or the copilot instructions.
