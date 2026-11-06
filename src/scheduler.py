"""
scheduler.py

Runs sync_all() in the background every few hours.
"""

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

import sync

SYNC_EVERY_HOURS = 3


def start_background_sync() -> BackgroundScheduler:
    """Start the background sync. It runs once right away, then every SYNC_EVERY_HOURS."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        sync.sync_all,
        trigger="interval",
        hours=SYNC_EVERY_HOURS,
        next_run_time=datetime.now(),   # first run starts right now
        max_instances=1,                # never run two syncs at the same time
        coalesce=True,                  # if runs were missed, do only one catch-up run
        id="umt_sync",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler