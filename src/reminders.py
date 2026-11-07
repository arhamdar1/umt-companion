"""
reminders.py

Two ways to remind the student about deadlines:

1. Windows notification (toast) shortly before each deadline.
2. An .ics calendar file. Thunderbird, Google Calendar, Outlook and others
   can import it, and each deadline gets its own alarm there too.

Reminders are read from the local database, so they work offline and never
talk to the LMS directly.
"""

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path

import db

# Send a toast this many hours before a deadline
REMINDER_HOURS = [24, 3]

# Pakistan Standard Time. Deadlines are stored as local time, so we use this
# to convert them to UTC for the .ics file.
PKT = timezone(timedelta(hours=5))

ICS_FOLDER = Path.home() / "Documents" / "UMT Companion"
ICS_PATH = ICS_FOLDER / "umt_deadlines.ics"

APP_NAME = "UMT Companion"


# ---------- Database table for "already sent" reminders ----------

def _ensure_table() -> None:
    """Create the table that remembers which reminders were already shown."""
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders_sent (
                event_id INTEGER NOT NULL,
                hours    INTEGER NOT NULL,
                sent_at  TEXT NOT NULL,
                PRIMARY KEY (event_id, hours)
            )
        """)


def _already_sent() -> set[tuple[int, int]]:
    """Return {(event_id, hours), ...} for every reminder shown before."""
    with db.connection() as conn:
        rows = conn.execute("SELECT event_id, hours FROM reminders_sent").fetchall()
    return {(r["event_id"], r["hours"]) for r in rows}


def _mark_sent(event_id: int, hours_list: list[int], now: datetime) -> None:
    """Remember that these reminder windows were handled, so they are not shown again."""
    rows = [(event_id, h, now.isoformat(timespec="seconds")) for h in hours_list]
    with db.connection() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO reminders_sent (event_id, hours, sent_at) VALUES (?, ?, ?)",
            rows,
        )


# ---------- Windows notification ----------

def show_toast(title: str, message: str) -> bool:
    """Show a Windows notification. Returns True if it was shown."""
    try:
        from winotify import Notification
    except ImportError:
        print("  [toast] winotify is not installed. Run:  pip install winotify")
        return False

    try:
        toast = Notification(app_id=APP_NAME, title=title, msg=message, duration="long")
        toast.show()
        return True
    except Exception as error:
        print(f"  [toast] could not show the notification: {error}")
        return False


def _time_left(delta: timedelta) -> str:
    """Turn a time difference into text like '3 hour(s)'."""
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} minute(s)"
    if minutes < 24 * 60:
        return f"{minutes // 60} hour(s)"
    return f"{minutes // (24 * 60)} day(s)"


def check_and_notify() -> int:
    """
    Look at every saved deadline and show a toast if a reminder window is open.

    If several windows are open at once (for example, the app was off and
    the deadline is only 2 hours away), we show ONE toast for the most urgent
    window and mark all of them as done.

    Returns how many toasts were shown.
    """
    db.init_db()
    _ensure_table()

    now = datetime.now()
    already = _already_sent()
    shown = 0

    for item in db.get_deadlines():
        due = item["due"]
        if now >= due:
            continue                                    # deadline already passed

        # Every reminder window that has started by now
        open_windows = [h for h in REMINDER_HOURS if now >= due - timedelta(hours=h)]
        if not open_windows:
            continue                                    # too early for any reminder

        # All of these windows were already handled before -> nothing new to say
        if all((item["event_id"], h) in already for h in open_windows):
            continue

        title = f"Deadline in {_time_left(due - now)}"
        message = f"{item['title']}\n{item['course']}\nDue {due:%a %d %b, %I:%M %p}"
        show_toast(title, message)

        _mark_sent(item["event_id"], open_windows, now)
        already.update((item["event_id"], h) for h in open_windows)
        shown += 1

    return shown


# ---------- .ics calendar file ----------

def _escape(text: str) -> str:
    """
    Get the text ready for a calendar file:
    1. turn '&amp;' back into '&' (Moodle sends titles in this encoded form)
    2. escape the characters calendar files need escaped
    """
    text = html.unescape(text)
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Calendar files want long lines split into pieces of about 70 characters."""
    if len(line) <= 70:
        return line
    parts = [line[:70]]
    rest = line[70:]
    while rest:
        parts.append(" " + rest[:69])
        rest = rest[69:]
    return "\r\n".join(parts)


def _utc_stamp(local_dt: datetime) -> str:
    """Convert a local (PKT) datetime into the UTC format calendars use, e.g. 20261107T185900Z."""
    aware = local_dt.replace(tzinfo=PKT)
    return aware.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def export_ics() -> tuple[Path, int]:
    """
    Write all UPCOMING deadlines to an .ics file.
    Returns (file path, number of events written).
    """
    db.init_db()
    ICS_FOLDER.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UMT Companion//Deadlines//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:UMT Deadlines",
    ]

    count = 0
    for item in db.get_deadlines():
        due = item["due"]
        if due < now:
            continue                                    # skip deadlines already passed

        summary = f"{item['title']} ({item['course']})"
        description = (
            f"Course: {item['course']}\n"
            f"Type: {item['activity_type']}\n"
            f"Link: {item['url']}"
        )

        lines += [
            "BEGIN:VEVENT",
            f"UID:deadline-{item['event_id']}@umt-companion",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART:{_utc_stamp(due)}",
            f"DTEND:{_utc_stamp(due + timedelta(minutes=30))}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(description)}",
        ]

        # One alarm per reminder window, built into the calendar app itself
        for h in REMINDER_HOURS:
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape(summary)} is due in {h} hours",
                f"TRIGGER:-PT{h}H",
                "END:VALARM",
            ]

        lines.append("END:VEVENT")
        count += 1

    lines.append("END:VCALENDAR")

    content = "\r\n".join(_fold(line) for line in lines) + "\r\n"

    # newline="" stops Windows from turning \r\n into \r\r\n
    with open(ICS_PATH, "w", encoding="utf-8", newline="") as file:
        file.write(content)

    return ICS_PATH, count