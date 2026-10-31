"""
phase3_test.py

Test for Phase 3.
    python src\\phase3_test.py              -> overdue (last 2 weeks) + all upcoming
    python src\\phase3_test.py --semester   -> full semester report
"""

import sys
from datetime import datetime

from credentials import load_credentials
from lms_client import LMSClient, LoginError, LMSConnectionError, LMSDataError


def time_left_text(due: datetime) -> str:
    """Turn a due date into text like '2d 5h left' or 'OVERDUE'."""
    difference = due - datetime.now()
    if difference.total_seconds() < 0:
        return "OVERDUE"
    days = difference.days
    hours = difference.seconds // 3600
    minutes = (difference.seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h left"
    return f"{hours}h {minutes}m left"


def show_deadlines(client: LMSClient):
    """Normal view: overdue (last 2 weeks) + all upcoming deadlines."""
    deadlines = client.get_deadlines()   # defaults: 14 days back, no limit ahead

    if not deadlines:
        print("No pending deadlines. Enjoy!")
        return

    print(f"{len(deadlines)} pending item(s):\n")
    for item in deadlines:
        # :>14 = right-align in 14 characters so the list lines up neatly
        print(f"[{time_left_text(item.due):>14}]  {item.due:%a %d %b, %I:%M %p}")
        print(f"    {item.title}")
        print(f"    Course: {item.course}  |  Type: {item.activity_type}")
        print(f"    {item.url}\n")


def show_semester(client: LMSClient):
    """Full semester report: every assignment, submitted or not."""
    print("Building semester report (opening each course)...\n")
    assignments = client.get_semester_assignments()

    if not assignments:
        print("No assignments found in your current courses.")
        return

    done = [a for a in assignments if a.submitted]
    pending = [a for a in assignments if not a.submitted]

    print(f"Total: {len(assignments)}   Submitted: {len(done)}   Not submitted: {len(pending)}\n")

    for a in assignments:
        mark = "[DONE]   " if a.submitted else "[PENDING]"
        due = a.due.strftime("%d %b %Y, %I:%M %p") if a.due else (a.due_text or "No due date")
        print(f"{mark} {a.title}")
        print(f"          {a.course}")
        print(f"          Due: {due}  |  Status: {a.status_text}  |  Grade: {a.grade}\n")


def main():
    # Use the login saved in Phase 2
    username, password = load_credentials("lms")
    if username is None:
        print("No saved LMS login. Run this first:  python src\\phase2_test.py")
        return

    client = LMSClient(username, password)

    try:
        client.login()
        print("[OK] Logged in.\n")

        if "--semester" in sys.argv:
            show_semester(client)
        else:
            show_deadlines(client)

    except LoginError as error:
        print(f"[FAIL] Login rejected: {error}")
    except LMSConnectionError as error:
        print(f"[NETWORK] {error}")
    except LMSDataError as error:
        print(f"[DATA] {error}")


# Run main() only when this file is run directly
if __name__ == "__main__":
    main()