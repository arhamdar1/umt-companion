"""
gcal_sync.py

Keeps your Google Calendar in step with the UMT deadlines:
- upcoming deadlines are ADDED or UPDATED
- deadlines that are no longer upcoming (submitted, or passed) are DELETED

Only events created by this app are ever deleted. Those are marked with a
private tag, or have an ID like 'deadline12345'. Your own events are never touched.

The first run opens a browser so you can log in and allow access.
After that, the saved token is reused automatically.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import db

# "events" scope = can create, change and delete events, nothing else
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

TIMEZONE = "Asia/Karachi"
REMINDER_MINUTES = [1440, 180]      # 24 hours and 3 hours before the deadline

FOLDER = Path.home() / "Documents" / "UMT Companion"
CREDENTIALS_PATH = FOLDER / "google_credentials.json"   # downloaded from Google Cloud
TOKEN_PATH = FOLDER / "google_token.json"               # created after first login

# Tag we add to every event this app creates, so we know which ones are ours
OWNER_TAG = {"umt_companion": "1"}

# Events created by the older version of this script look like 'deadline72797'
OLD_ID_PATTERN = re.compile(r"deadline\d+")

# How far back to look for our old events when cleaning up
CLEANUP_DAYS_BACK = 60


class GoogleSetupError(Exception):
    """Raised when the credentials file is missing."""


def _get_service():
    """Log in to Google (only the first time) and return the Calendar service."""
    FOLDER.mkdir(parents=True, exist_ok=True)

    if not CREDENTIALS_PATH.exists():
        raise GoogleSetupError(
            f"Google credentials file not found. Put google_credentials.json in:\n{FOLDER}"
        )

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())                       # renew silently, no browser
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)          # opens browser for login
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _google_id(event_id: int) -> str:
    """Google event IDs may only use lowercase letters a-v and digits."""
    return f"deadline{event_id}"


def _event_body(item) -> dict:
    """Build the Google Calendar event for one saved deadline."""
    due = item["due"]
    end = due
    summary = f"{item['title']} ({item['course']})"
    description = (
        f"Course: {item['course']}\n"
        f"Type: {item['activity_type']}\n"
        f"Link: {item['url']}"
    )
    return {
        "id": _google_id(item["event_id"]),
        "summary": summary,
        "description": description,
        "start": {"dateTime": due.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in REMINDER_MINUTES],
        },
        "extendedProperties": {"private": OWNER_TAG},
    }


def _is_our_event(event: dict) -> bool:
    """True only for events this app created (new tag, or the old 'deadlineNNN' ID)."""
    private = (event.get("extendedProperties") or {}).get("private") or {}
    if private.get("umt_companion") == "1":
        return True
    return bool(OLD_ID_PATTERN.fullmatch(event.get("id", "")))


def _list_our_events(service) -> list[dict]:
    """Read the calendar and return every event that this app created."""
    time_min = (datetime.now(timezone.utc) - timedelta(days=CLEANUP_DAYS_BACK)).isoformat()

    found = []
    page_token = None
    while True:
        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            singleEvents=True,
            maxResults=250,
            pageToken=page_token,
        ).execute()

        found.extend(e for e in result.get("items", []) if _is_our_event(e))

        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return found


def _delete_events_not_in(service, keep_ids: set[str]) -> int:
    """Delete our events whose IDs are no longer upcoming deadlines. Returns how many."""
    to_delete = [e["id"] for e in _list_our_events(service) if e["id"] not in keep_ids]

    deleted = 0
    for event_id in to_delete:
        try:
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            deleted += 1
        except HttpError as error:
            if error.resp.status not in (404, 410):    # already gone is fine
                raise
    return deleted


def sync_to_google() -> int:
    """
    Push all UPCOMING deadlines to Google Calendar, and remove the ones
    that are no longer upcoming. Returns how many events were added or updated.
    """
    db.init_db()
    service = _get_service()
    now = datetime.now()

    upcoming = [item for item in db.get_deadlines() if item["due"] >= now]
    keep_ids = {_google_id(item["event_id"]) for item in upcoming}

    count = 0
    for item in upcoming:
        body = _event_body(item)
        try:
            # Try to update first. If the event does not exist yet, Google says 404.
            service.events().update(
                calendarId="primary", eventId=body["id"], body=body
            ).execute()
        except HttpError as error:
            if error.resp.status != 404:
                raise
            service.events().insert(calendarId="primary", body=body).execute()
        count += 1

    # Safety: if the list is empty (for example, a failed LMS sync), do NOT
    # delete anything. Only clean up when we really have a current list.
    if keep_ids:
        removed = _delete_events_not_in(service, keep_ids)
        if removed:
            print(f"[google calendar] removed {removed} event(s) no longer upcoming")

    return count


# Run this file directly to test:  python src\gcal_sync.py
if __name__ == "__main__":
    try:
        total = sync_to_google()
        print(f"[OK] {total} deadline(s) are up to date in Google Calendar.")
    except GoogleSetupError as error:
        print(f"[SETUP] {error}")
    except Exception as error:
        print(f"[FAIL] {error}")