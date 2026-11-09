"""
assessments.py

Reads the marks (Quiz, Mid term, Final, Assignment, CP...) of each course
from the portal's 'My Courses' page, and saves them in the database.

How one course is read:
  1. Open My Courses fresh.
  2. Click the icon in the 'Assesment' column of that course's row.
  3. WAIT until the popup's table has real rows (the data loads a moment
     after the popup opens), or until the 'no assessments' message appears.
  4. Read the table and save it.

Retry rules:
  - Each course is tried up to ATTEMPTS_PER_COURSE times.
  - Courses that still fail are retried in extra rounds.
  - A course is saved as 'no marks' ONLY when the portal says so explicitly.
    A failed read never erases old saved marks.

Every successful check also saves a 'last checked' time for the course,
even when the course has no marks, so the app always shows when it looked.
"""

import re
import time
from datetime import datetime

from bs4 import BeautifulSoup

import db
from portal_client import BASE_URL, PortalDataError, clean_text

MY_COURSES_URL = f"{BASE_URL}/MyCourses"

ATTEMPTS_PER_COURSE = 4      # tries for one course in one round
WAIT_BEFORE_RETRY_S = 3      # wait before a retry (3s, 6s, 9s...)
EXTRA_ROUNDS = 3             # retry the failed courses this many extra rounds
WAIT_BETWEEN_ROUNDS_S = 20   # pause before each extra round
POPUP_WAIT_MS = 10000        # how long to wait for the popup's table to load

# The site spells it "Assesment" (one s), so we match 'assesm' and 'assessm'.
ASSESSMENT_WORDS = ("assesment", "assessment")
# Shown when the course has no assessments at all
NO_ASSESSMENT_WORDS = ("have assesment", "have assessment")


# ---------- Database ----------

def ensure_table() -> None:
    """Create the tables that hold the marks and the 'last checked' times."""
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS course_assessments (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id  TEXT NOT NULL,
                name       TEXT NOT NULL,
                total      TEXT,
                obtained   TEXT,
                assigned   TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS course_checked (
                course_id  TEXT PRIMARY KEY,
                checked_at TEXT NOT NULL
            )
        """)


def save_course(course_id: str, items: list[dict]) -> None:
    """
    Replace the saved marks of one course with the new list, and record
    the time it was checked (even if the list is empty).
    """
    now = datetime.now().isoformat(timespec="seconds")
    with db.connection() as conn:
        conn.execute("DELETE FROM course_assessments WHERE course_id = ?", (course_id,))
        conn.executemany(
            """INSERT INTO course_assessments
                   (course_id, name, total, obtained, assigned, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (course_id, i["name"], i["total"], i["obtained"], i["assigned"], now)
                for i in items
            ],
        )
        conn.execute(
            """INSERT INTO course_checked (course_id, checked_at)
               VALUES (?, ?)
               ON CONFLICT(course_id) DO UPDATE SET checked_at = excluded.checked_at""",
            (course_id, now),
        )


def load_all() -> dict:
    """
    Return {course_id: {'items': [...], 'updated_at': '...'}} for every course
    that was checked. 'updated_at' is the last checked time.
    """
    ensure_table()
    with db.connection() as conn:
        checks = conn.execute("SELECT course_id, checked_at FROM course_checked").fetchall()
        rows = conn.execute(
            "SELECT * FROM course_assessments ORDER BY course_id, id"
        ).fetchall()

    result = {
        c["course_id"]: {"items": [], "updated_at": c["checked_at"]}
        for c in checks
    }
    for row in rows:
        entry = result.setdefault(row["course_id"], {"items": [], "updated_at": row["updated_at"]})
        entry["items"].append({
            "name": row["name"],
            "total": row["total"],
            "obtained": row["obtained"],
            "assigned": row["assigned"],
        })
    return result


# ---------- Reading the portal ----------

def _row_for_course(page, course_id: str):
    """Find the table row whose ID cell is exactly this course id."""
    pattern = re.compile(rf"^\s*{re.escape(course_id)}\s*$")
    return page.locator("tr").filter(has=page.locator("td", has_text=pattern)).first


def _assessment_column_index(page) -> int:
    """
    Find the position (0, 1, 2...) of the column whose heading says 'Assesment'.
    Returns -1 if there is no such heading.
    """
    return page.evaluate(
        """() => {
            for (const table of document.querySelectorAll('table')) {
                const headers = Array.from(table.querySelectorAll('th'));
                const index = headers.findIndex(th => /assesm|assessm/i.test(th.innerText));
                if (index >= 0) return index;
            }
            return -1;
        }"""
    )


def _open_popups(page) -> list:
    """All popups that are open right now."""
    return page.locator(".modal.show").all()


def _close_all_popups(page) -> None:
    """Close every open popup (Close button, or Escape as a backup)."""
    for _ in range(5):
        if not _open_popups(page):
            return
        try:
            page.locator(".modal.show button:has-text('Close')").first.click(timeout=1500)
        except Exception:
            page.keyboard.press("Escape")
        page.wait_for_timeout(400)


def _popup_text(popup) -> str:
    try:
        return clean_text(popup.inner_text())
    except Exception:
        return ""


def _wait_for_assessment_popup(page, wait_ms: int):
    """
    Wait until an assessment popup is READY. Ready means one of:
      - it shows the 'no assessments' message  -> returns (popup, text, True)
      - its table has real data rows           -> returns (popup, text, False)
    If neither happens in time -> returns (None, last_text_seen, False).
    """
    last_text = ""
    end = time.time() + wait_ms / 1000
    while time.time() < end:
        for popup in _open_popups(page):
            text = _popup_text(popup)
            if not text:
                continue
            last_text = text
            lower = text.lower()
            if not any(word in lower for word in ASSESSMENT_WORDS):
                continue                           # some other popup
            if any(word in lower for word in NO_ASSESSMENT_WORDS):
                return popup, text, True
            if popup.locator("td").count() >= 4:   # a real data row has 4 cells
                return popup, text, False
        page.wait_for_timeout(400)
    return None, last_text, False


def _parse_table(html: str) -> list[dict]:
    """Read the marks table into a list of dictionaries."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for row in soup.find_all("tr"):
        if row.find("th"):
            continue                      # heading row
        cells = [clean_text(td.get_text()) for td in row.find_all("td")]
        if len(cells) >= 4:
            items.append({
                "name": cells[0],
                "total": cells[1],
                "obtained": cells[2],
                "assigned": cells[3],
            })
    return items


def _read_course_once(client, course_id: str) -> list[dict]:
    """
    One try: open My Courses fresh, click the Assesment icon, wait for the
    data, read it. Raises PortalDataError if this try did not work.
    """
    page = client.page
    client._open(page, MY_COURSES_URL)

    column = _assessment_column_index(page)
    if column < 0:
        raise PortalDataError("the 'Assesment' column was not found on the page")

    row = _row_for_course(page, course_id)
    if row.count() == 0:
        raise PortalDataError(f"course {course_id} not found on the page")

    # Only the cell in the Assesment column. Attendance is in another column.
    cell = row.locator("td").nth(column)
    clickable = cell.locator("a, button, svg, img, i, span").first
    target = clickable if clickable.count() > 0 else cell

    try:
        target.click(timeout=3000)
    except Exception as error:
        raise PortalDataError("could not click the assessment icon") from error

    popup, text, no_assessments = _wait_for_assessment_popup(page, POPUP_WAIT_MS)

    if popup is None:
        _close_all_popups(page)
        seen = f" Popup seen instead: '{text[:100]}'" if text else ""
        raise PortalDataError(f"assessment data did not load in time.{seen}")

    if no_assessments:
        _close_all_popups(page)
        return []                              # the portal really has no marks yet

    items = _parse_table(popup.inner_html())
    _close_all_popups(page)

    if not items:
        # The popup showed up but had no rows. Treat it as a failed try, not as 'no marks'.
        raise PortalDataError("popup opened but no marks were read")
    return items


def get_course_assessments(client, course_id: str) -> list[dict]:
    """
    Return the assessments of one course, with retries.
    e.g. [{'name': 'Quiz 1', 'total': '10.00', 'obtained': '0', 'assigned': '23/10/2026'}]
    Raises PortalDataError only after every attempt has failed.
    """
    last_error = None
    for attempt in range(1, ATTEMPTS_PER_COURSE + 1):
        try:
            return _read_course_once(client, course_id)
        except Exception as error:
            last_error = error
            if attempt < ATTEMPTS_PER_COURSE:
                wait = WAIT_BEFORE_RETRY_S * attempt
                print(f"  [retry] {course_id}: try {attempt} failed ({error}). "
                      f"Trying again in {wait}s...")
                time.sleep(wait)

    raise PortalDataError(f"failed after {ATTEMPTS_PER_COURSE} tries: {last_error}")


def sync_assessments(client, course_ids: list[str]) -> tuple[int, list[str]]:
    """
    Read and save the marks of every course, retrying the ones that fail.
    Returns (how many courses were saved, list of course ids still failing).
    A course that never succeeds keeps its old saved marks and old check time.
    """
    ensure_table()
    pending = list(course_ids)

    for round_number in range(1, EXTRA_ROUNDS + 2):      # first round + extra rounds
        if not pending:
            break
        if round_number > 1:
            print(f"  [marks] round {round_number}: retrying {len(pending)} course(s) "
                  f"after a {WAIT_BETWEEN_ROUNDS_S}s pause...")
            time.sleep(WAIT_BETWEEN_ROUNDS_S)

        still_failing = []
        for course_id in pending:
            try:
                items = get_course_assessments(client, course_id)
                save_course(course_id, items)
                print(f"  [marks] {course_id}: {len(items)} item(s)")
            except Exception as error:
                still_failing.append(course_id)
                print(f"  [marks skip] {course_id}: {error}")
        pending = still_failing

    saved = len(course_ids) - len(pending)
    return saved, pending


# Test:  python src\assessments.py
if __name__ == "__main__":
    import sys

    import credentials
    from portal_client import PortalClient

    username, password = credentials.load_credentials("portal")
    if username is None:
        print("No portal login saved. Run:  python src\\phase_test4.py")
        sys.exit(1)

    # show_browser=True: you can watch the clicks happen
    with PortalClient(username, password, show_browser=True) as portal:
        portal.login()
        course_ids = [s.course_id for s in portal.get_subjects()]
        saved, failed = sync_assessments(portal, course_ids)

    print(f"\nChecked {saved} course(s).")
    if failed:
        print("Still not read after all rounds:", ", ".join(failed))

    for course_id, entry in load_all().items():
        print(f"\n{course_id}: {len(entry['items'])} item(s), checked {entry['updated_at']}")
        for item in entry["items"]:
            print(f"   {item['name']:<15} total {item['total']:<7} "
                  f"obtained {item['obtained']:<7} {item['assigned']}")