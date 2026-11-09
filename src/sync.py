"""
sync.py

Pulls fresh data from the LMS and the Student Portal and saves it to the database.

Rules:
- A FAILED sync never deletes or overwrites good old data.
- A subject's new numbers are only saved if they look sane.
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


def _looks_valid(new, old) -> bool:
    """
    Decide whether one subject's new numbers are safe to save.
    new = freshly fetched Attendance, old = saved row (dict) or None.
    """
    if new.total <= 0:
        return False                      # nothing was read for this subject
    if new.attended < 0 or new.attended > new.total:
        return False                      # impossible numbers
    if old is not None and new.total < old["total"]:
        return False                      # lectures went DOWN = portal bug, keep old data
    return True


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
    """Fetch attendance and marks from the portal and save what looks sane."""
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

            # Old saved rows, so we can compare the new numbers against them
            old_rows = {row["assigned_id"]: row for row in db.get_attendance()}

            good = []
            rejected = []
            for subject in subjects:
                if _looks_valid(subject, old_rows.get(subject.assigned_id)):
                    good.append(subject)
                else:
                    rejected.append(subject.course_id)

            if not good:
                raise PortalDataError("No usable attendance could be read from the portal.")

            db.save_attendance(good)

            message = f"{len(good)} subject(s) saved."
            if rejected:
                message += f" Kept old data for: {', '.join(rejected)}."
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