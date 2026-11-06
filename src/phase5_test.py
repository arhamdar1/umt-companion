"""
phase5_test.py

Test for Phase 5.
    python src\\phase5_test.py          -> sync now, then show what is saved
    python src\\phase5_test.py --show   -> only show saved data (works offline)
    python src\\phase5_test.py --auto   -> background sync every 3 hours (Ctrl+C to stop)
"""

import sys
import time

import db
import sync
from scheduler import start_background_sync, SYNC_EVERY_HOURS


def show_sync_status():
    print("Sync status:")
    for source in ("lms", "portal"):
        status = db.get_sync_status(source)
        if status is None:
            print(f"  {source:<7} never synced yet")
        elif status["last_error"]:
            print(f"  {source:<7} LAST TRY FAILED at {status['last_attempt']}")
            print(f"          reason: {status['last_error']}")
            print(f"          showing data from: {status['last_success'] or 'never'}")
        else:
            print(f"  {source:<7} OK, last synced at {status['last_success']}")
    print()


def show_data():
    deadlines = db.get_deadlines()
    print(f"Deadlines saved: {len(deadlines)}")
    for d in deadlines:
        print(f"  {d['due']:%a %d %b %Y, %I:%M %p}  {d['title']}  ({d['course']})")
    print()

    attendance = db.get_attendance()
    print(f"Attendance saved: {len(attendance)} subject(s)")
    for a in attendance:
        percent = round(a["attended"] / a["total"] * 100, 1) if a["total"] else 0
        print(
            f"  {a['course_id']:<10} {a['attended']}/{a['total']:<4} "
            f"{percent:>5}%   (updated {a['updated_at']})"
        )
    print()


def main():
    db.init_db()
    print(f"Database: {db.DB_PATH}\n")

    if "--show" in sys.argv:
        show_sync_status()
        show_data()
        return

    if "--auto" in sys.argv:
        scheduler = start_background_sync()
        print(f"Auto-sync running, every {SYNC_EVERY_HOURS} hours. Press Ctrl+C to stop.\n")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            scheduler.shutdown()
            print("Stopped.")
        return

    print("Syncing now (this can take a minute or two)...\n")
    for result in sync.sync_all():
        mark = "[OK]  " if result.ok else "[FAIL]"
        print(f"{mark} {result.source}: {result.message}")
    print()

    show_sync_status()
    show_data()


if __name__ == "__main__":
    main()