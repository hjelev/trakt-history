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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

PRIMARY_USER = os.getenv('PRIMARY_USER')
ADDITIONAL_USERS_STR = os.getenv('ADDITIONAL_USERS', '')
ADDITIONAL_USERS = [u.strip() for u in ADDITIONAL_USERS_STR.split(',') if u.strip()]
ALL_USERS = [PRIMARY_USER] + ADDITIONAL_USERS

TRAKT_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_SCRIPT = os.path.join(TRAKT_DIR, 'scripts', 'update_trakt_local.py')

scheduler = None


def run_update_for_user(username):
    """Execute update_trakt_local.py for a specific user."""
    try:
        logger.info(f"Starting update for user: {username}")
        cmd = [
            sys.executable,
            UPDATE_SCRIPT,
            '--user', username
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode == 0:
            logger.info(f"✓ Update completed for {username}")
        else:
            logger.error(f"✗ Update failed for {username}: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error(f"✗ Update timed out for {username}")
    except Exception as e:
        logger.error(f"✗ Error updating {username}: {e}")


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
        return scheduler
    
    scheduler = BackgroundScheduler(daemon=True)
    
    # Schedule update every hour
    scheduler.add_job(
        update_all_users,
        trigger=IntervalTrigger(hours=1),
        id='update_all_users',
        name='Update Trakt history for all users',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Background scheduler started - will update all users every hour")
    
    return scheduler


def stop_scheduler():
    """Stop the background scheduler."""
    global scheduler
    
    if scheduler is not None:
        scheduler.shutdown()
        scheduler = None
        logger.info("Background scheduler stopped")


if __name__ == '__main__':
    logger.info("Starting scheduler test...")
    start_scheduler()
    
    try:
        import time
        logger.info("Scheduler running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
        stop_scheduler()
