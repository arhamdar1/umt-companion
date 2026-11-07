"""
phase6_test.py

Test for Phase 6.
    python src\\phase6_test.py          -> check reminders now + write the .ics file
    python src\\phase6_test.py --toast  -> show one test notification
    python src\\phase6_test.py --check  -> only check reminders now
    python src\\phase6_test.py --ics    -> only write the .ics file
"""

import sys

import db
import reminders


def main():
    db.init_db()

    # Only a notification test, nothing else
    if "--toast" in sys.argv:
        ok = reminders.show_toast(
            "UMT Companion test",
            "If you can see this, notifications work!",
        )
        print("[OK] Test notification sent." if ok else "[FAIL] Notification did not show.")
        return

    run_check = "--ics" not in sys.argv
    run_ics = "--check" not in sys.argv

    if run_check:
        shown = reminders.check_and_notify()
        print(f"[OK] Reminder check done. Notifications shown now: {shown}\n")

    if run_ics:
        path, count = reminders.export_ics()
        print(f"[OK] Calendar file written: {path}")
        print(f"     Upcoming deadlines in it: {count}\n")


if __name__ == "__main__":
    main()