#!/usr/bin/env python3
"""
Background task scheduler for automatic Trakt history updates.
Runs update_trakt_local.py every hour for all users.
"""

import os
import sys
import subprocess
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

# Setup logging with both console and file output
log_file = os.path.join(os.path.dirname(__file__), 'scheduler.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

PRIMARY_USER = os.getenv('PRIMARY_USER')
if not PRIMARY_USER:
    logger.error("PRIMARY_USER not set in .env file!")
    raise ValueError("PRIMARY_USER must be set in .env file")

ADDITIONAL_USERS_STR = os.getenv('ADDITIONAL_USERS', '')
ADDITIONAL_USERS = [u.strip() for u in ADDITIONAL_USERS_STR.split(',') if u.strip()]
ALL_USERS = [PRIMARY_USER] + ADDITIONAL_USERS

TRAKT_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_SCRIPT = os.path.join(TRAKT_DIR, 'scripts', 'update_trakt_local.py')

logger.info(f"Scheduler initialized: PRIMARY_USER={PRIMARY_USER}, ALL_USERS={ALL_USERS}")
logger.info(f"UPDATE_SCRIPT={UPDATE_SCRIPT}, exists={os.path.exists(UPDATE_SCRIPT)}")

scheduler = None


def run_update_for_user(username):
    """Execute update_trakt_local.py for a specific user."""
    try:
        logger.info(f"Starting update for user: {username}")
        
        # Verify the update script exists
        if not os.path.exists(UPDATE_SCRIPT):
            logger.error(f"✗ Update script not found: {UPDATE_SCRIPT}")
            return
        
        cmd = [
            sys.executable,
            UPDATE_SCRIPT,
            '--user', username
        ]
        # For primary user, force refresh to ensure ratings are always pulled fresh
        # For other users, use incremental mode (respects cache for faster updates)
        if username == PRIMARY_USER:
            cmd.append('--force')
        
        logger.debug(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode == 0:
            logger.info(f"✓ Update completed for {username}")
            # Log output for debugging
            if result.stdout:
                # Log last 10 lines
                lines = result.stdout.strip().split('\n')
                for line in lines[-10:]:
                    if line.strip():
                        logger.debug(f"  {line}")
        else:
            logger.error(f"✗ Update failed for {username}")
            logger.error(f"Return code: {result.returncode}")
            if result.stderr:
                logger.error(f"STDERR: {result.stderr}")
            if result.stdout:
                logger.error(f"STDOUT (last 20 lines):\n" + '\n'.join(result.stdout.split('\n')[-20:]))
    except subprocess.TimeoutExpired:
        logger.error(f"✗ Update timed out for {username} (timeout: 600s)")
    except Exception as e:
        logger.exception(f"✗ Error updating {username}: {e}")


def update_all_users():
    """Update watch history for all configured users."""
    logger.info(f"Starting scheduled update for all users: {ALL_USERS}")
    for username in ALL_USERS:
        run_update_for_user(username)
    logger.info("Scheduled update cycle completed")


def start_scheduler():
    """Start the background scheduler."""
    global scheduler
    
    if scheduler is not None:
        logger.warning("Scheduler already running")
        return scheduler
    
    try:
        scheduler = BackgroundScheduler(daemon=True)
        logger.info("✓ BackgroundScheduler created")
    except Exception as e:
        logger.error(f"✗ Failed to create BackgroundScheduler: {e}")
        logger.exception("Exception details:")
        return None
    
    try:
        # Schedule update every hour
        scheduler.add_job(
            update_all_users,
            trigger=IntervalTrigger(hours=1),
            id='update_all_users',
            name='Update Trakt history for all users',
            replace_existing=True
        )
        logger.info("✓ Job added to scheduler")
    except Exception as e:
        logger.error(f"✗ Failed to add job: {e}")
        logger.exception("Exception details:")
        return None
    
    try:
        scheduler.start()
        logger.info("✓ Background scheduler started - will update all users every hour")
        logger.info(f"  Jobs scheduled: {[job.name for job in scheduler.get_jobs()]}")
    except Exception as e:
        logger.error(f"✗ Failed to start scheduler: {e}")
        logger.exception("Exception details:")
        return None
    
    return scheduler


def stop_scheduler():
    """Stop the background scheduler."""
    global scheduler
    
    if scheduler is not None:
        scheduler.shutdown()
        scheduler = None
        logger.info("Background scheduler stopped")


if __name__ == '__main__':
    logger.info("=" * 70)
    logger.info("Starting scheduler (test mode)")
    logger.info("=" * 70)
    logger.info(f"Configuration:")
    logger.info(f"  PRIMARY_USER: {PRIMARY_USER}")
    logger.info(f"  ALL_USERS: {ALL_USERS}")
    logger.info(f"  UPDATE_SCRIPT: {UPDATE_SCRIPT}")
    logger.info(f"  Update script exists: {os.path.exists(UPDATE_SCRIPT)}")
    logger.info(f"  Python executable: {sys.executable}")
    logger.info("=" * 70)
    
    scheduler_instance = start_scheduler()
    
    if scheduler_instance is None:
        logger.error("Failed to start scheduler!")
        sys.exit(1)
    
    try:
        import time
        logger.info("Scheduler running. Press Ctrl+C to stop.")
        logger.info("Check scheduler.log for detailed output.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal (Ctrl+C)")
        stop_scheduler()
        logger.info("Scheduler stopped.")
    except Exception as e:
        logger.exception(f"Unexpected error in main loop: {e}")
        stop_scheduler()
        sys.exit(1)
