"""
portal_client.py

Handles the UMT Student Portal (ASP.NET + ReportViewer).
Uses Playwright so the JavaScript attendance report renders, then reads it.

Browser mode:
  - Normal use (the app's sync): runs in the background with NO window.
  - show_browser=True: opens a visible window (only for testing).

Attendance counting:
  attended = number of 'Present' entries
  total    = number of 'Present' + 'Absent' entries

Reading the report:
  A report counts as ready when either the 'Total Lectures' line OR the
  Present/Absent rows are visible. It is read repeatedly, and if the numbers
  keep changing, the latest reading is used instead of skipping the subject.
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

PAGE_TIMEOUT_MS = 60000      # how long to wait for a normal page
PAGE_RETRIES = 2             # try opening a normal page this many times
LOGIN_ATTEMPTS = 15          # retry the CAPTCHA this many times before giving up

REPORT_ATTEMPTS = 3          # try each subject's report this many times
REPORT_ATTEMPT_MS = 45000    # wait this long for one try, then start a new try
FRAME_WAIT_MS = 15000        # wait this long for the report frame to appear
STABLE_CHECKS = 2            # how many identical readings in a row we need
STABLE_GAP_MS = 1500         # pause between two readings
MAX_READINGS = 8             # after this many readings, use the latest one

# Ready = the summary line is shown, OR at least one Present/Absent cell is shown.
REPORT_READY_JS = """() => {
    const t = document.body ? document.body.innerText : '';
    if (/Total\\s*Lectures\\s*:?\\s*\\d+/i.test(t)) return true;
    const cells = Array.from(document.querySelectorAll('td, div, span'));
    return cells.some(e => /^(present|absent)$/i.test((e.innerText || '').trim()));
}"""


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
    Opens a browser, logs in, and reads attendance.

        with PortalClient(student_id, password) as portal:
            portal.login()
            subjects = portal.get_all_attendance()
    """

    def __init__(self, student_id: str, password: str, show_browser: bool = False):
        self.student_id = student_id
        self._password = password
        self._show = show_browser

        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None
        self.logged_in = False

    # ----- open / close the browser -----

    def __enter__(self):
        try:
            self._playwright = sync_playwright().start()

            if self._show:
                self._browser = self._playwright.chromium.launch(headless=False)
            else:
                self._browser = self._playwright.chromium.launch(
                    channel="chromium",
                    headless=True,
                )

            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 900}
            )
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

    # ----- opening pages -----

    def _open(self, page, url: str, tries: int = PAGE_RETRIES) -> None:
        """
        Open a page. Wait only for its HTML (domcontentloaded), and retry
        on timeout. Raises PortalConnectionError if every try fails.
        """
        last_error = None
        for _ in range(tries):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                return
            except PlaywrightTimeoutError as error:
                last_error = error
        raise PortalConnectionError(f"Could not open {url}: {last_error}")

    # ----- login (with CAPTCHA retry) -----

    def login(self) -> None:
        last_error_message = "Login failed."

        for attempt in range(1, LOGIN_ATTEMPTS + 1):
            self._open(self.page, LOGIN_URL)

            try:
                self.page.wait_for_selector("span.captcha", timeout=PAGE_TIMEOUT_MS)
                security_code = clean_text(self.page.locator("span.captcha").inner_text())
            except Exception as error:
                raise PortalDataError(f"Could not read the SecurityCode: {error}") from error

            try:
                self.page.fill('input[name="student_id"]', self.student_id)
                self.page.fill('input[name="Password"]', self._password)
                self.page.fill('input[name="SecurityCode"]', security_code)
                with self.page.expect_navigation(wait_until="domcontentloaded"):
                    self.page.press('input[name="SecurityCode"]', "Enter")
            except PlaywrightTimeoutError as error:
                raise PortalConnectionError(f"Login did not complete: {error}") from error
            except Exception as error:
                raise PortalDataError(f"Could not fill the login form: {error}") from error

            if "/Account/Login" not in self.page.url:
                self.logged_in = True
                return

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

        self._open(self.page, ATTENDANCE_LIST_URL)

        if "/Account/Login" in self.page.url:
            raise PortalDataError("Session expired. Please log in again.")

        try:
            self.page.wait_for_selector("a[data-assigned-id]", timeout=PAGE_TIMEOUT_MS)
        except PlaywrightTimeoutError as error:
            raise PortalDataError("No subjects found on the attendance page.") from error

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

    def _find_report_frame(self, tab, wait_ms: int = FRAME_WAIT_MS):
        """Wait (up to wait_ms) for the iframe that holds the report. Returns it or None."""
        waited = 0
        while waited <= wait_ms:
            for candidate in tab.frames:
                url = candidate.url or ""
                if "Attendance.aspx" in url or "/Reports/" in url:
                    return candidate
            tab.wait_for_timeout(500)
            waited += 500
        return None

    def _read_stable_report(self, tab, frame) -> str:
        """
        Read the report until STABLE_CHECKS readings in a row give the same
        numbers. If the numbers keep changing, the latest reading is used,
        as long as it has at least one lecture in it.
        """
        previous = None
        same_in_a_row = 0
        last_html = ""

        for _ in range(MAX_READINGS):
            frame.wait_for_function(REPORT_READY_JS, timeout=REPORT_ATTEMPT_MS)
            html = frame.content()
            last_html = html
            numbers = self._parse_report(html)

            if numbers == previous:
                same_in_a_row += 1
                if same_in_a_row >= STABLE_CHECKS:
                    return html
            else:
                same_in_a_row = 1
                previous = numbers

            tab.wait_for_timeout(STABLE_GAP_MS)

        # Numbers kept changing. Use the latest reading if it has real data.
        attended, total = self._parse_report(last_html)
        if total > 0:
            return last_html
        raise PortalDataError("the report had no lecture rows")

    def _load_report_html(self, subject: Attendance) -> str:
        """
        One try: open the subject's report in a FRESH tab and return its HTML.
        """
        tab = self._context.new_page()
        try:
            self._open(tab, f"{VIEW_ATTENDANCE_URL}?id={subject.assigned_id}", tries=1)

            frame = self._find_report_frame(tab)
            if frame is None:
                raise PortalDataError("the report frame did not appear")

            return self._read_stable_report(tab, frame)

        except PlaywrightTimeoutError as error:
            raise PortalDataError(
                f"report still loading after {REPORT_ATTEMPT_MS // 1000} seconds"
            ) from error
        finally:
            try:
                tab.close()
            except Exception:
                pass

    def get_attendance(self, subject: Attendance) -> None:
        """
        Fill in attended / total for one subject.
        Tries up to REPORT_ATTEMPTS times, each time in a fresh tab.
        """
        if not self.logged_in:
            raise PortalDataError("Not logged in yet. Call login() first.")

        last_error = None
        for attempt in range(1, REPORT_ATTEMPTS + 1):
            try:
                report_html = self._load_report_html(subject)
                attended, total = self._parse_report(report_html)
                subject.attended = attended
                subject.total = total
                return
            except (PortalConnectionError, PortalDataError) as error:
                last_error = error
                if attempt < REPORT_ATTEMPTS:
                    print(
                        f"  [retry] {subject.course_id}: try {attempt} failed "
                        f"({error}), trying again..."
                    )
                    self.page.wait_for_timeout(2000)

        raise PortalDataError(
            f"could not load after {REPORT_ATTEMPTS} tries: {last_error}"
        )

    @staticmethod
    def _parse_report(html: str) -> tuple[int, int]:
        """
        Count each 'Present' / 'Absent' text exactly once.
        We look at TEXT nodes, not tags, so nested wrappers are not counted twice.
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
            except Exception as error:
                print(f"  [skip] {subject.course_id}: unexpected problem: {error}")
        return subjects