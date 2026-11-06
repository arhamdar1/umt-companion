"""
sync.py

Pulls fresh data from the LMS and the Student Portal and saves it to the database.

The most important rule: a FAILED sync never deletes or overwrites good old data.
If the portal is down, the attendance saved last time is still there.
"""

from dataclasses import dataclass

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
            # Catch-all so one unexpected bug can't crash the background job
            result = SyncResult("lms", False, f"Unexpected error: {error}")

    db.record_sync(result.source, result.ok, result.message)
    return result


def sync_portal() -> SyncResult:
    """Fetch attendance from the portal and save it per subject."""
    student_id, password = credentials.load_credentials("portal")
    if student_id is None:
        result = SyncResult("portal", False, "No portal login saved yet.")
    else:
        try:
            with PortalClient(student_id, password) as portal:
                portal.login()
                subjects = portal.get_all_attendance()

            # Subjects with total == 0 were not read properly, so don't save them
            good = [s for s in subjects if s.total > 0]
            if not good:
                raise PortalDataError("No attendance could be read from the portal.")

            db.save_attendance(good)

            skipped = len(subjects) - len(good)
            message = f"{len(good)} subject(s) saved."
            if skipped:
                message += f" {skipped} kept their old data."
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
    return [sync_lms(), sync_portal()]