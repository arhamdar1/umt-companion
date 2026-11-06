"""
downloader.py

Downloads the files attached to each PENDING assignment (PDF, Word, text, slides...)
and saves them in folders: one folder per course, one sub-folder per assignment.

    Documents\\UMT Companion\\Assignments\\
        Database Systems (Lab)\\
            ASSIGNMENT 1\\
                brief.pdf

Only PENDING assignments are downloaded:
    - submitted assignments: skipped
    - overdue assignments (due date passed, not submitted): skipped
    - pending assignments (not submitted, due date still coming): downloaded

Files are saved OUTSIDE the project folder, so they never reach GitHub.

Run:
    python src\\downloader.py                         -> pending, current semester
    python src\\downloader.py --semester "fall 2025"  -> pending, one semester
    python src\\downloader.py --all                   -> pending, all time

Files that already exist are skipped, so you can run it again safely.
"""

import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from credentials import load_credentials
from lms_client import (
    BASE_URL,
    TIMEOUT_SECONDS,
    LMSClient,
    LoginError,
    LMSConnectionError,
    LMSDataError,
)
from semester import current_semester, parse_semester_name

# Where the files go. Documents is outside the project, so GitHub never sees them.
DOWNLOAD_ROOT = Path.home() / "Documents" / "UMT Companion" / "Assignments"

DELAY_BETWEEN_FILES = 0.5     # small pause so we don't hammer the LMS
MAX_NAME_LENGTH = 100         # keep Windows folder/file names short

# Characters Windows does not allow in file or folder names
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Wide date range used for --all
ALL_TIME_START = datetime(2000, 1, 1)
ALL_TIME_END = datetime(2100, 1, 1)


def safe_name(text: str) -> str:
    """Make text safe to use as a Windows folder or file name."""
    cleaned = INVALID_CHARS.sub("_", text)
    cleaned = " ".join(cleaned.split()).strip(" .")
    cleaned = cleaned[:MAX_NAME_LENGTH].rstrip(" .")
    return cleaned or "untitled"


def is_pending(assignment, now: datetime) -> bool:
    """
    True only if NOT submitted AND the due date is still in the future.
    Submitted or overdue assignments return False.
    """
    if assignment.submitted:
        return False
    if assignment.due is None:
        return False
    return assignment.due >= now


def find_attachment_links(client: LMSClient, assignment_url: str) -> list[str]:
    """Return the download links of the files attached to one assignment."""
    try:
        response = client.session.get(assignment_url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as error:
        raise LMSConnectionError(f"Could not open the assignment: {error}") from error

    if "/login/" in response.url:
        raise LMSDataError("Session expired. Please log in again.")

    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(assignment_url, a["href"])
        # Files attached by the teacher have "/mod_assign/intro" in their link.
        # Files you uploaded as a submission use a different path, so they are skipped.
        if "pluginfile.php" in href and "/mod_assign/intro" in href and href not in links:
            links.append(href)
    return links


def filename_from(response, file_url: str) -> str:
    """Get the real file name from the server's headers, or from the link itself."""
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disposition, re.IGNORECASE)
    if match:
        name = unquote(match.group(1))
    else:
        name = unquote(urlparse(file_url).path.split("/")[-1])
    return safe_name(name)


def download_file(client: LMSClient, file_url: str, folder: Path) -> tuple[str, str]:
    """
    Download one file into `folder`.
    Returns ('saved', name) or ('exists', name). Raises an error if it fails.
    """
    response = client.session.get(file_url, stream=True, timeout=TIMEOUT_SECONDS)
    try:
        response.raise_for_status()

        # A web page instead of a file usually means we are not allowed to open it
        if "text/html" in response.headers.get("Content-Type", ""):
            raise LMSDataError("the LMS sent a web page instead of the file")

        name = filename_from(response, file_url)
        target = folder / name
        if target.exists():
            return "exists", name

        folder.mkdir(parents=True, exist_ok=True)
        try:
            with open(target, "wb") as file:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    file.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)   # remove a half-written file
            raise
        return "saved", name
    finally:
        response.close()


def pick_period():
    """
    Decide which period to look at, from the command line.
    Returns (start, end, label), or (None, None, message) if the input is wrong.
    """
    if "--all" in sys.argv:
        return ALL_TIME_START, ALL_TIME_END, "all time"

    if "--semester" in sys.argv:
        index = sys.argv.index("--semester")
        if index + 1 < len(sys.argv) and not sys.argv[index + 1].startswith("--"):
            semester = parse_semester_name(sys.argv[index + 1])
            if semester is None:
                return None, None, 'Please write it like "fall 2025" or "spring 2025".'
            return semester.start, semester.end, semester.name

    # Default: the semester running today
    semester = current_semester()
    if semester is None:
        return None, None, (
            "Today is in the break (26 Jul to 30 Sep), no semester is running.\n"
            'Use  --semester "fall 2025"  or  --all'
        )
    return semester.start, semester.end, semester.name


def download_all(client: LMSClient, start: datetime, end: datetime, label: str) -> None:
    """Find every PENDING assignment in the period and download its attached files."""
    print(f"Looking for pending assignments in: {label}\n")
    everything = client.get_semester_assignments(start, end)

    # Keep only the assignments that are not submitted and not yet overdue
    now = datetime.now()
    assignments = [a for a in everything if is_pending(a, now)]
    skipped = len(everything) - len(assignments)

    if not assignments:
        print("No pending assignments in this period.")
        if skipped:
            print(f"({skipped} submitted or overdue assignment(s) were skipped.)")
        return

    print(f"{len(assignments)} pending assignment(s) found "
          f"({skipped} submitted or overdue skipped).\n")

    saved = existing = no_files = failed = 0

    for a in assignments:
        if not a.url:
            continue

        assignment_url = urljoin(BASE_URL, a.url)
        folder = DOWNLOAD_ROOT / safe_name(a.course) / safe_name(a.title)

        try:
            links = find_attachment_links(client, assignment_url)
        except (LMSDataError, LMSConnectionError) as error:
            print(f"[FAIL] {a.course} / {a.title}: {error}")
            failed += 1
            continue

        if not links:
            no_files += 1
            continue

        print(f"{a.course}  >  {a.title}")
        for link in links:
            try:
                status, name = download_file(client, link, folder)
            except Exception as error:
                print(f"   [FAIL] {error}")
                failed += 1
                continue

            if status == "saved":
                print(f"   saved:   {name}")
                saved += 1
            else:
                print(f"   exists:  {name}")
                existing += 1

            time.sleep(DELAY_BETWEEN_FILES)
        print()

    print("-" * 60)
    print(f"Files saved: {saved}   already there: {existing}   "
          f"pending with no files: {no_files}   failed: {failed}")
    print(f"\nFolder: {DOWNLOAD_ROOT}")


def main():
    start, end, label = pick_period()
    if start is None:
        print(label)   # label holds the problem message in this case
        return

    username, password = load_credentials("lms")
    if username is None:
        print("No saved LMS login. Run this first:  python src\\phase2_test.py")
        return

    client = LMSClient(username, password)
    try:
        client.login()
        print("[OK] Logged in.\n")
        download_all(client, start, end, label)
    except LoginError as error:
        print(f"[FAIL] Login rejected: {error}")
    except LMSConnectionError as error:
        print(f"[NETWORK] {error}")
    except LMSDataError as error:
        print(f"[DATA] {error}")


if __name__ == "__main__":
    main()