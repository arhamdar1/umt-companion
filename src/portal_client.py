"""
portal_client.py

Handles the UMT Student Portal (ASP.NET + ReportViewer).
Uses Playwright so the JavaScript attendance report renders, then reads it.

Attendance counting:
  attended = number of 'Present' entries
  total    = number of 'Present' + 'Absent' entries
Unmarked / missing lectures are ignored.

Login: the SecurityCode is plain text on the page, but the page can refresh
between reading it and submitting, which changes the code. So we read + submit
immediately, and retry if the portal says 'Invalid Code'.
"""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---------- Addresses ----------
BASE_URL = "https://online.umt.edu.pk"
LOGIN_URL = f"{BASE_URL}/Account/Login"
ATTENDANCE_LIST_URL = f"{BASE_URL}/Attendance"
VIEW_ATTENDANCE_URL = f"{BASE_URL}/Attendance/ViewAttendance"   # needs ?id=...

PAGE_TIMEOUT_MS = 30000
REPORT_TIMEOUT_MS = 60000
LOGIN_ATTEMPTS = 15         # retry the CAPTCHA this many times before giving up


# ---------- Custom errors ----------

class PortalLoginError(Exception):
    """Wrong student ID / password."""


class PortalConnectionError(Exception):
    """Portal unreachable (no internet, site down, timeout)."""


class PortalDataError(Exception):
    """Portal answered, but not with the data we expected."""


# ---------- Helpers ----------

def clean_text(text: str) -> str:
    return " ".join(text.split())


# ---------- Data structure ----------

@dataclass
class Attendance:
    course_id: str
    title: str
    faculty: str
    attended: int
    total: int
    assigned_id: str

    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.attended / self.total * 100, 1)

    @property
    def is_low(self) -> bool:
        return self.percentage < 75.0


# ---------- The client ----------

class PortalClient:
    """
    Opens a headless browser, logs in, and reads attendance.

        with PortalClient(student_id, password) as portal:
            portal.login()
            subjects = portal.get_all_attendance()
    """

    def __init__(self, student_id: str, password: str, show_browser: bool = False):
        self.student_id = student_id
        self._password = password
        self._headless = not show_browser

        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None
        self.logged_in = False

    # ----- open / close the browser -----

    def __enter__(self):
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self._headless)
            self._context = self._browser.new_context()
            self._context.set_default_timeout(PAGE_TIMEOUT_MS)
            self.page = self._context.new_page()
        except Exception as error:
            raise PortalConnectionError(f"Could not start the browser: {error}") from error
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        for obj, method in ((self._browser, "close"), (self._playwright, "stop")):
            try:
                if obj is not None:
                    getattr(obj, method)()
            except Exception:
                pass

    # ----- login (with CAPTCHA retry) -----

    def login(self) -> None:
        last_error_message = "Login failed."

        for attempt in range(1, LOGIN_ATTEMPTS + 1):
            try:
                # Always start from a fresh login page so the CAPTCHA is current
                self.page.goto(LOGIN_URL)
            except PlaywrightTimeoutError as error:
                raise PortalConnectionError(f"Could not open the login page: {error}") from error

            # Read the SecurityCode text, then fill + submit immediately
            try:
                security_code = clean_text(self.page.locator("span.captcha").inner_text())
            except Exception as error:
                raise PortalDataError(f"Could not read the SecurityCode: {error}") from error

            try:
                self.page.fill('input[name="student_id"]', self.student_id)
                self.page.fill('input[name="Password"]', self._password)
                self.page.fill('input[name="SecurityCode"]', security_code)
                with self.page.expect_navigation():
                    self.page.press('input[name="SecurityCode"]', "Enter")
            except PlaywrightTimeoutError as error:
                raise PortalConnectionError(f"Login did not complete: {error}") from error
            except Exception as error:
                raise PortalDataError(f"Could not fill the login form: {error}") from error

            # Success = we're no longer on a login page
            if "/Account/Login" not in self.page.url:
                self.logged_in = True
                return

            # Read the portal's error message
            message = "Login failed."
            try:
                box = self.page.locator(".validation-summary-errors, .text-danger").first
                if box.count() > 0:
                    text = clean_text(box.inner_text())
                    if text:
                        message = text
            except Exception:
                pass
            last_error_message = message

            # 'Invalid Code' = wrong CAPTCHA -> try again with a fresh one.
            # Anything else (e.g. wrong password) -> stop now, retrying won't help.
            if "code" not in message.lower():
                raise PortalLoginError(message)

            print(f"  [retry] CAPTCHA attempt {attempt} failed, trying again...")

        raise PortalLoginError(
            f"Could not pass the security code after {LOGIN_ATTEMPTS} tries "
            f"(last message: {last_error_message})."
        )

    # ----- subjects list -----

    def get_subjects(self) -> list[Attendance]:
        if not self.logged_in:
            raise PortalDataError("Not logged in yet. Call login() first.")

        try:
            self.page.goto(ATTENDANCE_LIST_URL)
        except PlaywrightTimeoutError as error:
            raise PortalConnectionError(f"Could not open the attendance page: {error}") from error

        if "/Account/Login" in self.page.url:
            raise PortalDataError("Session expired. Please log in again.")

        rows = self.page.eval_on_selector_all(
            "a[data-assigned-id]",
            """els => els.map(a => {
                const tr = a.closest('tr');
                const tds = tr ? Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim()) : [];
                return { id: a.getAttribute('data-assigned-id'), cells: tds };
            })"""
        )

        subjects = []
        for row in rows:
            cells = row["cells"]
            if len(cells) < 5:
                continue
            subjects.append(
                Attendance(
                    course_id=clean_text(cells[0]),
                    title=clean_text(cells[1]),
                    faculty=clean_text(cells[4]),
                    attended=0,
                    total=0,
                    assigned_id=row["id"],
                )
            )

        if not subjects:
            raise PortalDataError("No subjects found on the attendance page.")

        return subjects

    # ----- one subject's attendance -----

    def get_attendance(self, subject: Attendance) -> None:
        """Open the subject's report in a FRESH tab and read attended / total."""
        if not self.logged_in:
            raise PortalDataError("Not logged in yet. Call login() first.")

        tab = self._context.new_page()
        tab.set_default_timeout(PAGE_TIMEOUT_MS)
        try:
            tab.goto(f"{VIEW_ATTENDANCE_URL}?id={subject.assigned_id}")

            frame = None
            for _ in range(3):
                for candidate in tab.frames:
                    url = candidate.url or ""
                    if "Attendance.aspx" in url or "/Reports/" in url:
                        frame = candidate
                        break
                if frame is not None:
                    break
                tab.wait_for_timeout(1500)
            if frame is None:
                raise PortalDataError("Could not find the report frame.")

            # Wait until the summary line ('Total Lectures : N') is rendered,
            # which means the whole table has finished loading.
            frame.wait_for_function(
                """() => {
                    const t = document.body ? document.body.innerText : '';
                    return /Total\\s*Lectures\\s*:?\\s*\\d+/i.test(t);
                }""",
                timeout=REPORT_TIMEOUT_MS,
            )

            report_html = frame.content()
        except PlaywrightTimeoutError as error:
            raise PortalDataError(
                f"Report did not load in time for {subject.course_id}: {error}"
            ) from error
        finally:
            try:
                tab.close()
            except Exception:
                pass

        attended, total = self._parse_report(report_html)
        subject.attended = attended
        subject.total = total

    @staticmethod
    def _parse_report(html: str) -> tuple[int, int]:
        """
        Count each 'Present' / 'Absent' text exactly once.

        We look at TEXT nodes, not tags. A tag like <div> wrapping <div>
        wrapping the word 'Present' would otherwise be counted once per
        wrapper, which is why numbers came out 3x too big.
        """
        soup = BeautifulSoup(html, "html.parser")

        present = 0
        absent = 0
        for text_node in soup.find_all(string=True):
            value = clean_text(str(text_node)).lower()
            if value == "present":
                present += 1
            elif value == "absent":
                absent += 1

        return present, present + absent

    # ----- everything at once -----

    def get_all_attendance(self) -> list[Attendance]:
        subjects = self.get_subjects()
        for subject in subjects:
            try:
                self.get_attendance(subject)
            except (PortalConnectionError, PortalDataError) as error:
                print(f"  [skip] {subject.course_id}: {error}")
        return subjects