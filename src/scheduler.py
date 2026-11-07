"""
scheduler.py

Background jobs:
  - every 3 hours : sync LMS + portal, refresh the .ics file,
                    and push deadlines to Google Calendar
  - every 15 min  : check deadlines and show Windows reminders
"""

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

import gcal_sync
import reminders
import sync

SYNC_EVERY_HOURS = 3
CHECK_REMINDERS_EVERY_MINUTES = 15


def _sync_everything() -> None:
    """Sync LMS and portal, then update the calendar file and Google Calendar."""
    sync.sync_all()
    reminders.export_ics()
    try:
        total = gcal_sync.sync_to_google()
        print(f"[google calendar] {total} deadline(s) up to date")
    except Exception as error:
        # Google being unavailable must not stop the other jobs
        print(f"[google calendar] sync failed: {error}")


def _check_reminders() -> None:
    """Run the reminder check. An error here must not stop the scheduler."""
    try:
        reminders.check_and_notify()
    except Exception as error:
        print(f"[reminder check failed] {error}")


def start_background_sync() -> BackgroundScheduler:
    """Start all background jobs. Each one runs right away, then on its own schedule."""
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        _sync_everything,
        trigger="interval",
        hours=SYNC_EVERY_HOURS,
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
        id="umt_sync",
        replace_existing=True,
    )

    scheduler.add_job(
        _check_reminders,
        trigger="interval",
        minutes=CHECK_REMINDERS_EVERY_MINUTES,
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
        id="umt_reminders",
        replace_existing=True,
    )

    scheduler.start()
    return scheduler