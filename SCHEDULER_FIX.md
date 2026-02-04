# Scheduler Fix Summary

## Issues Found & Fixed

### 1. **Insufficient Logging**
- **Problem**: The original scheduler didn't write logs to a file, making it impossible to debug issues when running in the background.
- **Fix**: Added file logging to `scheduler.log` in addition to console output at DEBUG level.

### 2. **Silent Failures in start_scheduler()**
- **Problem**: If the BackgroundScheduler failed to initialize or add jobs, there was no error reporting and the function would continue without raising an exception.
- **Fix**: Added try-except blocks with proper error logging and return value to indicate success/failure.

### 3. **Insufficient Error Details in run_update_for_user()**
- **Problem**: When a subprocess failed, only the stderr was logged, making it hard to understand what went wrong.
- **Fix**: 
  - Check if UPDATE_SCRIPT exists before running
  - Log the full command being executed
  - Log both stdout (last 20 lines) and stderr when failures occur
  - Added DEBUG logging for script output
  - Used `logger.exception()` for full traceback

### 4. **Better Startup Diagnostics**
- **Problem**: When run manually, the scheduler provided minimal feedback about what was configured.
- **Fix**: Added detailed startup logging showing:
  - Configuration values (PRIMARY_USER, ALL_USERS)
  - Script path and existence check
  - Python executable path
  - Job details after starting

### 5. **PRIMARY_USER Validation**
- **Problem**: If PRIMARY_USER wasn't set in .env, the scheduler would fail with unclear error messages.
- **Fix**: Added explicit check and error message at startup.

## Changes Made to scheduler.py

1. **Logging Setup** (Lines 16-24):
   - Added FileHandler to write to `scheduler.log`
   - Added StreamHandler for console output
   - Set level to DEBUG for detailed logging

2. **Initialization** (Lines 29-47):
   - Added validation for PRIMARY_USER
   - Added initialization logging

3. **run_update_for_user()** (Lines 50-93):
   - Added script existence check
   - Added command logging
   - Improved error reporting with full stdout/stderr
   - Added `logger.exception()` for full tracebacks

4. **start_scheduler()** (Lines 103-140):
   - Wrapped scheduler creation in try-except
   - Added validation checks at each step
   - Return None on failure for explicit error handling
   - Log job details after starting

5. **__main__ block** (Lines 159-187):
   - Added configuration display
   - Added startup validation
   - Better error handling and exit codes
   - Added note about log file location

## Testing

Run the scheduler manually to verify it works:

```bash
python scheduler.py
```

Check the log file for detailed output:

```bash
tail -f scheduler.log
```

The first update will be scheduled 1 hour after startup. To test immediately, you can manually run:

```bash
python scripts/update_trakt_local.py --user masoko --force
python scripts/update_trakt_local.py --user petrovgeorgi6
```

## Integration with app.py

The Flask app already imports and uses the scheduler:
- Starts on app startup via `start_scheduler()`
- Gracefully stops on app shutdown via `stop_scheduler()`
- All logs go to `scheduler.log` for debugging

## Systemd Service

If using the systemd service (`trakt-app.service`), check logs with:

```bash
journalctl -u trakt-app -f
tail -f /home/masoko/git/trakt/scheduler.log
```
