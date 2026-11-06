"""
semester.py

Works out which semester a date belongs to, and its start / end dates.

Fall   : 1 Oct  -> 25 Feb (next year)   e.g. Fall 2026   = 1 Oct 2026 to 25 Feb 2027
Spring : 1 Mar  -> 25 Jul               e.g. Spring 2025 = 1 Mar 2025 to 25 Jul 2025
Break  : 26 Jul -> 30 Sep               no semester running
"""

import re
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class Semester:
    name: str            # e.g. "Fall 2026"
    start: datetime      # first moment of the semester
    end: datetime        # last moment of the semester (end of the last day)


def _fall(year: int) -> Semester:
    """Fall that STARTS in `year` (1 Oct) and ends in the next year (25 Feb)."""
    return Semester(
        name=f"Fall {year}",
        start=datetime(year, 10, 1, 0, 0, 0),
        end=datetime(year + 1, 2, 25, 23, 59, 59),
    )


def _spring(year: int) -> Semester:
    """Spring of `year`: 1 Mar to 25 Jul."""
    return Semester(
        name=f"Spring {year}",
        start=datetime(year, 3, 1, 0, 0, 0),
        end=datetime(year, 7, 25, 23, 59, 59),
    )


def semester_for_date(day: date) -> Semester | None:
    """Return the semester a date falls in, or None during the break."""
    month_day = (day.month, day.day)

    if month_day >= (10, 1):                 # Oct, Nov, Dec -> Fall this year
        return _fall(day.year)
    if month_day <= (2, 25):                 # Jan, Feb -> Fall that started last year
        return _fall(day.year - 1)
    if (3, 1) <= month_day <= (7, 25):       # Mar to Jul 25 -> Spring this year
        return _spring(day.year)
    return None                              # Jul 26 to Sep 30 -> break


def current_semester() -> Semester | None:
    """The semester running today, or None during the break."""
    return semester_for_date(date.today())


def parse_semester_name(text: str) -> Semester | None:
    """
    Turn text like 'fall 2026' or 'Spring 2025' into a Semester.
    Returns None if the text is not in that form.
    """
    match = re.fullmatch(r"\s*(fall|spring)\s+(\d{4})\s*", text, re.IGNORECASE)
    if match is None:
        return None

    season = match.group(1).lower()
    year = int(match.group(2))
    return _fall(year) if season == "fall" else _spring(year)