"""
lms_client.py

Handles everything related to UMT LMS (which runs on Moodle):
- logging in
- fetching upcoming deadlines (dashboard Timeline)
- building a full-semester assignment report (submitted / not submitted)
"""

import re
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ---------- Addresses (found during DevTools recon) ----------
BASE_URL = "https://lms.umt.edu.pk"
LOGIN_URL = f"{BASE_URL}/login/index.php"
AJAX_URL = f"{BASE_URL}/lib/ajax/service.php"           # Moodle's internal API
ASSIGN_INDEX_URL = f"{BASE_URL}/mod/assign/index.php"    # "all assignments in a course" page

TIMEOUT_SECONDS = 20

# Small pause between page loads so we don't hammer the LMS server
DELAY_BETWEEN_PAGES = 0.5


# ---------- Custom errors ----------

class LoginError(Exception):
    """Raised when the LMS rejects the username/password."""


class LMSConnectionError(Exception):
    """Raised when the LMS can't be reached (no internet, site down, timeout)."""


class LMSDataError(Exception):
    """Raised when the LMS answers, but not with the data we expected."""


# ---------- Helpers ----------

def clean_text(text: str) -> str:
    """Remove extra spaces, tabs and new lines: 'Data  Science' -> 'Data Science'."""
    return " ".join(text.split())


def parse_moodle_date(text: str):
    """
    Turn Moodle's date text into a real datetime.
    Example inputs:
        'Saturday, 24 October 2026, 11:59 PM'
        'Saturday, 24 October 2026, 23:59'
    Returns None if the text isn't a date (e.g. '-' when there is no due date).
    """
    for date_format in ("%A, %d %B %Y, %I:%M %p", "%A, %d %B %Y, %H:%M"):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue    # try the next format
    return None


# ---------- Data structures ----------

@dataclass
class Deadline:
    """One pending item from the dashboard Timeline."""
    event_id: int        # Moodle's unique ID for this item
    title: str           # e.g. "Assignment 2"
    course: str          # e.g. "Data Structures"
    due: datetime        # due date and time (local time)
    activity_type: str   # "assign", "quiz", etc.
    url: str             # link to open it in the browser

    @property
    def is_overdue(self) -> bool:
        return self.due < datetime.now()


@dataclass
class SemesterAssignment:
    """One assignment from a course's 'all assignments' page."""
    course: str
    title: str
    due: datetime | None   # None if the assignment has no due date
    due_text: str          # original text from the page, e.g. 'Saturday, 24 October 2026, 11:59 PM'
    submitted: bool        # True = you've submitted it
    status_text: str       # original status, e.g. 'Submitted for grading' / 'No submission'
    grade: str             # e.g. '8.00 / 10.00' or '-'
    url: str


# ---------- The client ----------

class LMSClient:
    """A logged-in 'browser session' with the UMT LMS."""

    def __init__(self, username: str, password: str):
        self.username = username
        self._password = password          # underscore = "private, don't print this"
        self.session = requests.Session()  # remembers cookies like a browser
        self.logged_in = False
        self.sesskey = None                # Moodle's security key, needed for API calls

    # ===== Login =====

    def login(self) -> None:
        """Log into the LMS. Raises LMSConnectionError, LoginError or LMSDataError."""

        # 1. Open login page to get the hidden 'logintoken'
        try:
            response = self.session.get(LOGIN_URL, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as error:
            raise LMSConnectionError(f"Could not open the LMS login page: {error}") from error

        soup = BeautifulSoup(response.text, "html.parser")
        token_input = soup.find("input", {"name": "logintoken"})

        # 2. Send the login form
        payload = {
            "anchor": "",
            "logintoken": token_input["value"] if token_input else "",
            "username": self.username,
            "password": self._password,
        }
        try:
            response = self.session.post(LOGIN_URL, data=payload, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as error:
            raise LMSConnectionError(f"Could not send the login form: {error}") from error

        # 3. Still on a /login/ page = login failed
        if "/login/" in response.url:
            soup = BeautifulSoup(response.text, "html.parser")
            error_box = soup.find(id="loginerrormessage") or soup.find(class_="alert-danger")
            message = (
                error_box.get_text(strip=True)
                if error_box
                else "Login failed. Please check your username and password."
            )
            raise LoginError(message)

        # 4. Find the sesskey in the page's JavaScript:  "sesskey":"AbC123"
        match = re.search(r'"sesskey":"([^"]+)"', response.text)
        if not match:
            raise LMSDataError("Logged in, but could not find the session key (sesskey).")

        self.sesskey = match.group(1)
        self.logged_in = True

    # ===== Internal helpers =====

    def _call_api(self, method_name: str, args: dict) -> dict:
        """Call one Moodle API method (like the dashboard does) and return its 'data'."""
        if not self.logged_in:
            raise LMSDataError("Not logged in yet. Call login() first.")

        body = [{"index": 0, "methodname": method_name, "args": args}]
        params = {"sesskey": self.sesskey, "info": method_name}

        try:
            response = self.session.post(AJAX_URL, params=params, json=body, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as error:
            raise LMSConnectionError(f"Could not reach the LMS API: {error}") from error

        try:
            result = response.json()[0]
        except (ValueError, IndexError, KeyError) as error:
            raise LMSDataError(f"LMS sent an unexpected answer for {method_name}.") from error

        if result.get("error"):
            exception = result.get("exception") or {}
            code = exception.get("errorcode", "unknown")
            message = exception.get("message", "")
            raise LMSDataError(f"LMS error ({code}): {message}")

        return result["data"]

    def _get_page(self, url: str, params: dict | None = None) -> BeautifulSoup:
        """Open a normal LMS page and return it ready for searching."""
        try:
            response = self.session.get(url, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as error:
            raise LMSConnectionError(f"Could not open {url}: {error}") from error

        # If Moodle sent us back to the login page, our session has expired
        if "/login/" in response.url:
            raise LMSDataError("Session expired. Please log in again.")

        return BeautifulSoup(response.text, "html.parser")

    # ===== Feature 1: deadlines (normal view) =====

    def get_deadlines(self, days_back: int = 14, days_ahead: int | None = None,
                      limit: int = 50) -> list[Deadline]:
        """
        Pending items from the dashboard Timeline.

        days_back:  include overdue items from the last N days (Moodle itself uses 14)
        days_ahead: only items due within the next N days.
                    Use None to get everything, no matter how far away.
        """
        now = int(time.time())          # "Unix time" = seconds since 1 Jan 1970
        one_day = 24 * 60 * 60

        args = {
            "limitnum": limit,
            "timesortfrom": now - days_back * one_day,
            "limittononsuspendedevents": True,
        }
        if days_ahead is not None:
            args["timesortto"] = now + days_ahead * one_day

        data = self._call_api("core_calendar_get_action_events_by_timesort", args)

        deadlines = []
        for event in data.get("events", []):
            deadlines.append(
                Deadline(
                    event_id=event["id"],
                    title=clean_text(event.get("activityname") or event.get("name", "Untitled")),
                    course=clean_text((event.get("course") or {}).get("fullname", "Unknown course")),
                    due=datetime.fromtimestamp(event["timesort"]),
                    activity_type=event.get("modulename") or event.get("eventtype", ""),
                    url=event.get("url", ""),
                )
            )

        deadlines.sort(key=lambda d: d.due)
        return deadlines

    # ===== Feature 2: full semester report =====

    def get_current_courses(self) -> list[tuple[int, str]]:
        """Return [(course_id, course_name), ...] for courses you're currently enrolled in."""
        data = self._call_api(
            "core_course_get_enrolled_courses_by_timeline_classification",
            {"offset": 0, "limit": 0, "classification": "inprogress", "sort": "fullname"},
        )
        return [(course["id"], clean_text(course["fullname"])) for course in data.get("courses", [])]

    def _get_course_assignments(self, course_id: int, course_name: str) -> list[SemesterAssignment]:
        """Read the 'all assignments' table of ONE course."""
        soup = self._get_page(ASSIGN_INDEX_URL, params={"id": course_id})

        table = soup.find("table", class_="generaltable")
        if table is None:
            return []   # this course has no assignments

        # Read the column headings, e.g. ['topic', 'assignments', 'due date', 'submission', 'grade']
        header_row = table.find("tr")
        headers = [clean_text(th.get_text()).lower() for th in header_row.find_all("th")]

        def find_column(*words):
            """Return the position of the first heading that contains any of these words."""
            for index, heading in enumerate(headers):
                if any(word in heading for word in words):
                    return index
            return None

        name_col = find_column("assignment")
        due_col = find_column("due")
        status_col = find_column("submission")
        grade_col = find_column("grade")

        if name_col is None:
            raise LMSDataError(f"Unexpected assignments table layout in '{course_name}'.")

        assignments = []
        for row in table.find_all("tr")[1:]:          # [1:] skips the heading row
            cells = row.find_all(["td", "th"])   # count both cell types so columns line up
            if len(cells) <= name_col:
                continue                              # empty / divider row

            link = cells[name_col].find("a")
            if link is None:
                continue                              # not an assignment row

            def cell_text(col):
                return clean_text(cells[col].get_text()) if col is not None and col < len(cells) else ""

            due_text = cell_text(due_col)
            status_text = cell_text(status_col)
            status_lower = status_text.lower()

            # 'Submitted for grading' -> True
            # 'No submission' / 'Draft (not submitted)' -> False
            submitted = (
                "submitted" in status_lower
                and "not submitted" not in status_lower
                and "no submission" not in status_lower
            )

            assignments.append(
                SemesterAssignment(
                    course=course_name,
                    title=clean_text(link.get_text()),
                    due=parse_moodle_date(due_text),
                    due_text=due_text,
                    submitted=submitted,
                    status_text=status_text,
                    grade=cell_text(grade_col),
                    url=link.get("href", ""),
                )
            )

        return assignments

    def get_semester_assignments(self) -> list[SemesterAssignment]:
        """Every assignment in every current course, with submitted / not submitted status."""
        all_assignments = []

        for course_id, course_name in self.get_current_courses():
            all_assignments.extend(self._get_course_assignments(course_id, course_name))
            time.sleep(DELAY_BETWEEN_PAGES)   # be polite to the server

        # Sort by due date; assignments without a due date go to the end
        all_assignments.sort(key=lambda a: a.due or datetime.max)
        return all_assignments