"""
phase3_test.py

Test for Phase 3.
    python src\\phase3_test.py                          -> overdue (2 weeks) + all upcoming
    python src\\phase3_test.py --semester               -> CURRENT semester report
    python src\\phase3_test.py --semester "spring 2025" -> report for that semester
    python src\\phase3_test.py --semester "fall 2025"   -> report for that semester

Semester report statuses:
    [DONE]     submitted
    [OVERDUE]  not submitted, due date already passed
    [PENDING]  not submitted, due date still coming
"""

import sys
from datetime import datetime

from credentials import load_credentials
from lms_client import LMSClient, LoginError, LMSConnectionError, LMSDataError
from semester import current_semester, parse_semester_name, Semester


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


def get_requested_semester():
    """
    Read '--semester' from the command line.
    Returns (Semester, None) on success, or (None, error message).
    """
    index = sys.argv.index("--semester")

    # A name was typed after --semester, e.g. "spring 2025"
    if index + 1 < len(sys.argv) and not sys.argv[index + 1].startswith("--"):
        semester = parse_semester_name(sys.argv[index + 1])
        if semester is None:
            return None, 'Please write it like "fall 2026" or "spring 2025".'
        return semester, None

    # No name given -> use the semester running today
    semester = current_semester()
    if semester is None:
        return None, (
            "Today is in the break (26 Jul to 30 Sep), no semester is running.\n"
            'Give a name instead, e.g.  --semester "fall 2025"'
        )
    return semester, None


def show_deadlines(client: LMSClient):
    """Normal view: overdue (last 2 weeks) + all upcoming deadlines."""
    deadlines = client.get_deadlines()   # defaults: 14 days back, no limit ahead

    if not deadlines:
        print("No pending deadlines. Enjoy!")
        return

    print(f"{len(deadlines)} pending item(s):\n")
    for item in deadlines:
        print(f"[{time_left_text(item.due):>14}]  {item.due:%a %d %b, %I:%M %p}")
        print(f"    {item.title}")
        print(f"    Course: {item.course}  |  Type: {item.activity_type}")
        print(f"    {item.url}\n")


def status_label(assignment, now: datetime) -> str:
    """
    Decide DONE / OVERDUE / PENDING for one assignment.
    Labels are all 9 characters long so the columns line up.
    """
    if assignment.submitted:
        return "[DONE]   "
    if assignment.due < now:
        return "[OVERDUE]"
    return "[PENDING]"


def show_semester(client: LMSClient, semester: Semester):
    """Semester report: every assignment due inside this semester's dates."""
    print(f"Semester: {semester.name}  "
          f"({semester.start:%d %b %Y} to {semester.end:%d %b %Y})\n")
    print("Building report (checking each course, this takes a little while)...\n")

    assignments = client.get_semester_assignments(semester.start, semester.end)

    if not assignments:
        print("No assignments with a due date in this semester.")
        return

    now = datetime.now()
    labels = [status_label(a, now) for a in assignments]

    done_count = labels.count("[DONE]   ")
    overdue_count = labels.count("[OVERDUE]")
    pending_count = labels.count("[PENDING]")

    print(f"Total: {len(assignments)}   Done: {done_count}   "
          f"Overdue: {overdue_count}   Pending: {pending_count}\n")

    for a, label in zip(assignments, labels):
        print(f"{label} {a.title}")
        print(f"          {a.course}")
        print(f"          Due: {a.due:%d %b %Y, %I:%M %p}  |  Status: {a.status_text}  |  Grade: {a.grade}\n")


def main():
    # Work out which report is wanted BEFORE logging in (no point logging in for a typo)
    semester = None
    if "--semester" in sys.argv:
        semester, problem = get_requested_semester()
        if problem:
            print(problem)
            return

    username, password = load_credentials("lms")
    if username is None:
        print("No saved LMS login. Run this first:  python src\\phase2_test.py")
        return

    client = LMSClient(username, password)

    try:
        client.login()
        print("[OK] Logged in.\n")

        if semester is not None:
            show_semester(client, semester)
        else:
            show_deadlines(client)

    except LoginError as error:
        print(f"[FAIL] Login rejected: {error}")
    except LMSConnectionError as error:
        print(f"[NETWORK] {error}")
    except LMSDataError as error:
        print(f"[DATA] {error}")


if __name__ == "__main__":
    main()