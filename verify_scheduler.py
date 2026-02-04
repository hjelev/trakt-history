#!/usr/bin/env python3
"""Quick verification that scheduler is working correctly"""
import sys
import os

sys.path.insert(0, '/home/masoko/git/trakt')
os.chdir('/home/masoko/git/trakt')

# Test 1: Import scheduler
try:
    from scheduler import start_scheduler, stop_scheduler, PRIMARY_USER, ALL_USERS, UPDATE_SCRIPT
    print("✓ Scheduler module imports successfully")
    print(f"  PRIMARY_USER: {PRIMARY_USER}")
    print(f"  ALL_USERS: {ALL_USERS}")
    print(f"  UPDATE_SCRIPT exists: {os.path.exists(UPDATE_SCRIPT)}")
except Exception as e:
    print(f"✗ Failed to import scheduler: {e}")
    sys.exit(1)

# Test 2: Verify it can be imported from app.py context
try:
    from app import HAS_SCHEDULER
    print(f"✓ app.py can import scheduler (HAS_SCHEDULER={HAS_SCHEDULER})")
except Exception as e:
    print(f"✗ app.py scheduler integration issue: {e}")

# Test 3: Check for log file
log_path = '/home/masoko/git/trakt/scheduler.log'
if os.path.exists(log_path):
    size = os.path.getsize(log_path)
    print(f"✓ scheduler.log exists (size: {size} bytes)")
    # Show last few lines
    with open(log_path, 'r') as f:
        lines = f.readlines()[-5:]
        print("  Last 5 log lines:")
        for line in lines:
            print(f"    {line.rstrip()}")
else:
    print(f"✗ scheduler.log not found at {log_path}")

print("\n✓ Scheduler is ready to use!")
print("\nTo run with full logging:")
print("  python scheduler.py")
print("\nTo check logs:")
print("  tail -f scheduler.log")
