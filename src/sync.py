"""
sync.py

Pulls fresh data from the LMS and the Student Portal and saves it to the database.

Rules:
- A FAILED sync never deletes or overwrites good old data.
- A subject is saved when its numbers are valid (total above 0, attended not
  more than total).
- After a successful portal sync, attendance rows that the portal no longer
  lists for the current student are removed. This clears old subjects left
  behind by a previous student.
- The marks (assessments) are read in the same portal session as attendance.
- The sync always runs in the background (no browser window).
- The GUI never talks to the portal or LMS directly. It only reads the database.
"""

from dataclasses import dataclass

import assessments
import credentials
import db
from lms_client import (
    LMSClient,
    LoginError as LMSLoginError,
    LMSConnectionError,
    LMSDataError,
)
from portal_client import (
    PortalClient,
    PortalLoginError,
    PortalConnectionError,
    PortalDataError,
)


@dataclass
class SyncResult:
    source: str     # 'lms' or 'portal'
    ok: bool        # True if this sync worked
    message: str    # short human-readable summary


def _looks_valid(new) -> bool:
    """
    Decide whether one subject's new numbers are safe to save.
    new = freshly fetched Attendance.
    """
    if new.total <= 0:
        return False                      # nothing was read for this subject
    if new.attended < 0 or new.attended > new.total:
        return False                      # impossible numbers
    return True


def _remove_stale_attendance(current_ids: set) -> int:
    """
    Delete saved attendance rows that the portal did not list this time.
    These are subjects left behind by a previous student. Returns how many were removed.
    """
    with db.connection() as conn:
        rows = conn.execute("SELECT assigned_id FROM attendance").fetchall()
        stale = [(r["assigned_id"],) for r in rows if r["assigned_id"] not in current_ids]
        conn.executemany("DELETE FROM attendance WHERE assigned_id = ?", stale)
    return len(stale)


def sync_lms() -> SyncResult:
    """Fetch deadlines from the LMS and replace the saved list."""
    username, password = credentials.load_credentials("lms")
    if username is None:
        result = SyncResult("lms", False, "No LMS login saved yet.")
    else:
        try:
            client = LMSClient(username, password)
            client.login()
            deadlines = client.get_deadlines()
            db.replace_deadlines(deadlines)
            result = SyncResult("lms", True, f"{len(deadlines)} deadline(s) saved.")
        except (LMSLoginError, LMSConnectionError, LMSDataError) as error:
            result = SyncResult("lms", False, str(error))
        except Exception as error:
            result = SyncResult("lms", False, f"Unexpected error: {error}")

    db.record_sync(result.source, result.ok, result.message)
    return result


def sync_portal() -> SyncResult:
    """Fetch attendance and marks from the portal and save what looks valid."""
    student_id, password = credentials.load_credentials("portal")
    if student_id is None:
        result = SyncResult("portal", False, "No portal login saved yet.")
    else:
        try:
            # No show_browser here: the sync always runs in the background
            with PortalClient(student_id, password) as portal:
                portal.login()
                subjects = portal.get_all_attendance()

                # Marks are read in the same session, so no second login is needed
                marks_saved, marks_failed = assessments.sync_assessments(
                    portal, [s.course_id for s in subjects]
                )

            good = []
            rejected = []
            for subject in subjects:
                if _looks_valid(subject):
                    good.append(subject)
                else:
                    rejected.append(subject.course_id)

            if not good:
                raise PortalDataError("No usable attendance could be read from the portal.")

            db.save_attendance(good)

            # Every subject the portal listed for THIS student, valid or not.
            # Anything saved that is not in this list belongs to someone else.
            current_ids = {s.assigned_id for s in subjects}
            removed = _remove_stale_attendance(current_ids)

            message = f"{len(good)} subject(s) saved."
            if rejected:
                message += f" Kept old data for: {', '.join(rejected)}."
            if removed:
                message += f" Removed {removed} old subject(s) from a previous student."
            message += f" Marks checked for {marks_saved} course(s)."
            if marks_failed:
                message += f" Marks not read for: {', '.join(marks_failed)}."
            result = SyncResult("portal", True, message)

        except (PortalLoginError, PortalConnectionError, PortalDataError) as error:
            result = SyncResult("portal", False, str(error))
        except Exception as error:
            result = SyncResult("portal", False, f"Unexpected error: {error}")

    db.record_sync(result.source, result.ok, result.message)
    return result


def sync_all() -> list[SyncResult]:
    """Run both syncs. One failing does not stop the other."""
    db.init_db()
    assessments.ensure_table()
    return [sync_lms(), sync_portal()]