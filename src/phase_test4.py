"""
phase_test4.py

Test for Phase 4: log into the Student Portal and print every subject's attendance.

First run : asks for your portal student ID + password, saves them securely.
Next runs : uses the saved ones (no typing).
Reset     : python src\\phase_test4.py --reset
"""

import sys
from getpass import getpass

from credentials import save_credentials, load_credentials, delete_credentials
from portal_client import (
    PortalClient,
    PortalLoginError,
    PortalConnectionError,
    PortalDataError,
)

SITE = "portal"   # saved separately from the "lms" login


def ask_and_save():
    """Ask for the portal login and store it in Windows Credential Manager."""
    student_id = input("Portal student ID: ").strip()
    password = getpass("Portal password (hidden while typing): ")
    save_credentials(SITE, student_id, password)
    print("[OK] Saved securely in Windows Credential Manager.\n")
    return student_id, password


def main():
    # "--reset" forgets the saved portal login
    if "--reset" in sys.argv:
        delete_credentials(SITE)
        print("[OK] Saved portal login deleted.")
        return

    student_id, password = load_credentials(SITE)
    if student_id is None:
        print("No saved portal login found.")
        student_id, password = ask_and_save()
    else:
        print(f"Using saved portal login for: {student_id}\n")

    subjects = []

    # show_browser=True opens a visible window so you can watch it work.
    # Change to False later for silent background runs.
    with PortalClient(student_id, password, show_browser=True) as client:
        try:
            client.login()
            print("[OK] Portal login successful. Fetching attendance...\n")
            subjects = client.get_all_attendance()

        except PortalLoginError as error:
            print(f"[FAIL] Login rejected: {error}")
            delete_credentials(SITE)
            print("Saved login removed. Run again to re-enter it.")
            return
        except PortalConnectionError as error:
            print(f"[NETWORK] {error}")
            return
        except PortalDataError as error:
            print(f"[DATA] {error}")
            return

    # ---- Print a neat table ----
    print(f"\n{'Course':<10} {'Title':<34} {'Att':>7} {'Absent':>7} {'%':>8}")
    print("-" * 72)

    low_subjects = []
    for s in subjects:
        if s.total == 0:
            att = "-"
            absent_text = "-"
            pct = "-"
        else:
            absent = s.total - s.attended     # absences = total lectures - present
            att = f"{s.attended}/{s.total}"
            absent_text = str(absent)
            pct = f"{s.percentage}%"
            if s.is_low:
                low_subjects.append(s)

        title = (s.title[:33] + "…") if len(s.title) > 34 else s.title
        print(f"{s.course_id:<10} {title:<34} {att:>7} {absent_text:>7} {pct:>8}")

    print("-" * 72)

    # ---- Warn about low attendance ----
    if low_subjects:
        print("\n⚠ Below 75% in:")
        for s in low_subjects:
            print(f"   {s.course_id} - {s.title}  ({s.percentage}%)")
    elif subjects:
        print("\nAll subjects at or above 75%.")


if __name__ == "__main__":
    main()