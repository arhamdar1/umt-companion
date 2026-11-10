"""
gui.py

The main window of UMT Companion.

Look & feel:
  - dark gradient background with soft glowing spots
  - rounded cards and pill-shaped tabs
  - fade-in animation when the window opens
  - animated "Syncing..." button
  - the Logins dialog uses the same look
  - clicking anywhere outside a table's rows clears its selection
  - table headers and cells are aligned the same way in every table

Tabs:
  - Deadlines       : upcoming and overdue items, with summary cards
  - Attendance      : per-subject attendance, red below 80%
  - Assessments     : each course with the time it was last checked.
                      Click a course to see all its marks (Quiz, Mid term, Final...)
  - Semester report : every assignment in a chosen semester (DONE / OVERDUE / PENDING)
  - Settings        : sync log and shortcuts to the folders

If you change to a DIFFERENT student ID in Logins, the previous student's
saved deadlines, attendance and marks are deleted (after asking you first).

The window only READS the database. Long jobs run in background threads,
so the window never freezes.
"""

import os
import sys
from datetime import datetime

from PyQt6.QtCore import QEvent, QModelIndex, QPointF, QPropertyAnimation, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QRadialGradient
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import assessments
import credentials
import db
import gcal_sync
import reminders
import sync
from lms_client import LMSClient
from semester import current_semester, parse_semester_name

APP_VERSION = "1.0"
DEVELOPER = "Developed by Arham Dar"

REFRESH_SECONDS = 60        # reload the tables from the database this often
URGENT_HOURS = 24           # deadlines within this many hours show in orange
LOW_ATTENDANCE = 80.0       # below this percentage, show in red
PASS_MARKS = 50.0           # below this percentage of marks, show in red
FADE_MS = 350               # how long the window fade-in takes
TIME_FORMAT = "%d %b %Y, %I:%M %p"   # e.g. "08 Nov 2026, 01:25 PM"

# How each activity type is shown in the Deadlines "Type" column
ACTIVITY_NAMES = {
    "assign": "Assignment",
    "quiz": "Quiz",
    "forum": "Forum",
    "lesson": "Lesson",
}

# Colours used across the app
GREEN = "#3ddc84"
RED = "#ff5c5c"
ORANGE = "#ffb84d"
BLUE = "#5ac8fa"
NORMAL = "#e8ecf5"
SOFT_BLUE = "#b8c7e6"       # used for course names and 'last checked' times
DIM = "#7d8899"             # used for 'not checked yet'

# Heading colours for some table columns (change these to taste)
HEADER_COLORS = {
    "Course": BLUE,
    "Attended": ORANGE,
    "Absent": RED,
}

APP_STYLE = """
QWidget {
    color: #e8ecf5;
    font-family: 'Segoe UI';
    font-size: 10pt;
    background: transparent;
}
QDialog { background-color: #161c2d; }
QFrame#card {
    background-color: rgba(255, 255, 255, 18);
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 14px;
}
QLabel#statTitle { color: #9fb0cc; font-size: 9pt; }
QLabel#statValue { font-size: 20pt; font-weight: bold; color: #ffffff; }
QLabel#appTitle { font-size: 22pt; font-weight: bold; color: #ffffff; }
QLabel#appSub { color: #9fb0cc; }
QLabel#sectionTitle { font-size: 12pt; font-weight: bold; color: #ffffff; }
QLabel#footer { color: #6f7d96; font-size: 9pt; }
QPushButton {
    background-color: rgba(255, 255, 255, 20);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 35);
    border-radius: 10px;
    padding: 8px 16px;
}
QPushButton:hover { background-color: rgba(255, 255, 255, 40); }
QPushButton:disabled { color: #7d8899; }
QPushButton#accent {
    background-color: #4f7cff;
    border: none;
    font-weight: bold;
}
QPushButton#accent:hover { background-color: #6b92ff; }
QPushButton#accent:disabled { background-color: #33407a; color: #aab4d4; }
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: rgba(255, 255, 255, 12);
    color: #9fb0cc;
    padding: 9px 18px;
    margin-right: 6px;
    border-radius: 10px;
}
QTabBar::tab:selected { background: #4f7cff; color: #ffffff; font-weight: bold; }
QTabBar::tab:hover:!selected { background: rgba(255, 255, 255, 25); color: #ffffff; }

/* ----- tables: clean rows, no boxes, one calm selection colour ----- */
QTableWidget {
    background-color: rgba(10, 14, 25, 150);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 12px;
    gridline-color: transparent;
    outline: 0;
}
QTableWidget::item {
    background-color: transparent;
    border: none;
    padding: 8px;
}
QTableWidget::item:selected {
    background-color: rgba(79, 124, 255, 70);
    color: #ffffff;
    border: none;
}
QTableWidget::item:focus {
    border: none;
    outline: none;
}
QHeaderView::section {
    background-color: rgba(255, 255, 255, 16);
    padding: 8px;
    border: none;
    font-weight: bold;
}
QTableCornerButton::section { background: transparent; border: none; }

QLineEdit, QComboBox, QTextEdit {
    background-color: rgba(10, 14, 25, 170);
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 8px;
    padding: 6px;
}
QLineEdit:focus { border: 1px solid #4f7cff; }
QComboBox QAbstractItemView {
    background-color: #1c2338;
    selection-background-color: #4f7cff;
    border-radius: 8px;
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 50); border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QMessageBox QLabel { color: #e8ecf5; }
"""


class CleanTable(QTableWidget):
    """
    A table that clears its selection when you click an empty area
    (below the last row, or beside the rows), and never shows a focus box.
    """

    def __init__(self, rows: int, columns: int, parent=None):
        super().__init__(rows, columns, parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Watch clicks on the table's drawing area (the viewport)
        self.viewport().installEventFilter(self)

    def clear_selection_now(self):
        """Forget the selected row(s) and the current cell."""
        self.clearSelection()
        self.setCurrentIndex(QModelIndex())

    def eventFilter(self, obj, event):
        if (
            obj is self.viewport()
            and event.type() == QEvent.Type.MouseButtonPress
            and not self.indexAt(event.position().toPoint()).isValid()
        ):
            self.clear_selection_now()
        return super().eventFilter(obj, event)


def make_table(headers: list[str], center_cols=()) -> QTableWidget:
    """
    A styled table. Columns listed in center_cols are centred, both the
    heading and the cells under it. All other columns are left-aligned.
    """
    table = CleanTable(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(False)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    for col, name in enumerate(headers):
        header_item = table.horizontalHeaderItem(col)
        if col in center_cols:
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            header_item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        # Colour some headings (see HEADER_COLORS at the top of this file)
        if name in HEADER_COLORS:
            header_item.setForeground(QColor(HEADER_COLORS[name]))
    return table


class GradientWidget(QWidget):
    """The background: a dark gradient with two soft glowing spots."""

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()

        gradient = QLinearGradient(0, 0, w, h)
        gradient.setColorAt(0.0, QColor("#0d1322"))
        gradient.setColorAt(0.5, QColor("#141a33"))
        gradient.setColorAt(1.0, QColor("#24173f"))
        painter.fillRect(self.rect(), QBrush(gradient))

        painter.setPen(Qt.PenStyle.NoPen)
        big = max(w, h)
        self._glow(painter, w * 0.85, h * 0.08, big * 0.45, QColor(79, 124, 255, 70))
        self._glow(painter, w * 0.08, h * 0.95, big * 0.40, QColor(160, 90, 255, 55))
        painter.end()

    @staticmethod
    def _glow(painter, cx, cy, radius, color):
        glow = QRadialGradient(cx, cy, radius)
        glow.setColorAt(0.0, color)
        fade_out = QColor(color)
        fade_out.setAlpha(0)
        glow.setColorAt(1.0, fade_out)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)


def make_stat(title: str):
    """A small rounded card with a title and a big number. Returns (card, number_label)."""
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 12, 18, 12)

    title_label = QLabel(title)
    title_label.setObjectName("statTitle")
    value_label = QLabel("-")
    value_label.setObjectName("statValue")

    layout.addWidget(title_label)
    layout.addWidget(value_label)
    return card, value_label


def attendance_color(percent: float) -> str:
    """Red below 80%, green at 80% or more."""
    return RED if percent < LOW_ATTENDANCE else GREEN


def absent_color(absent: int) -> str:
    """Red if any lecture was missed, green if none."""
    return RED if absent > 0 else GREEN


def marks_color(percent: float) -> str:
    """Red below the pass mark, green at or above it."""
    return RED if percent < PASS_MARKS else GREEN


def _number(text):
    """'8.50' -> 8.5. Returns None if the text is not a number (for example '-')."""
    try:
        return float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def fmt(number: float) -> str:
    """Show marks without extra zeros: 10.00 -> '10', 8.50 -> '8.5'."""
    return f"{number:.2f}".rstrip("0").rstrip(".")


def course_summary(items: list[dict]):
    """
    Add up one course's marks. Returns (obtained, total, percent).
    percent is None if there is no total to compare with.
    """
    obtained_sum = 0.0
    total_sum = 0.0
    for item in items:
        total = _number(item["total"])
        obtained = _number(item["obtained"])
        if total is None:
            continue
        total_sum += total
        if obtained is not None:
            obtained_sum += obtained

    percent = round(obtained_sum / total_sum * 100, 1) if total_sum else None
    return obtained_sum, total_sum, percent


def semester_choices() -> list[str]:
    """The items in the semester dropdown: 'Current semester', then the last 4 years."""
    year = datetime.now().year
    choices = ["Current semester"]
    for y in range(year, year - 4, -1):
        choices.append(f"Fall {y}")
        choices.append(f"Spring {y}")
    return choices


def pretty_time(text: str) -> str:
    """Turn a saved time like '2026-11-08T13:25:30' into '08 Nov 2026, 01:25 PM'."""
    if not text:
        return "never"
    return datetime.fromisoformat(text).strftime(TIME_FORMAT)


def time_left_text(due: datetime, now: datetime) -> str:
    """Text like '2d 5h' or '3h 10m', or 'OVERDUE'."""
    difference = due - now
    if difference.total_seconds() < 0:
        return "OVERDUE"
    days = difference.days
    hours = difference.seconds // 3600
    minutes = (difference.seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"


def make_item(text, center: bool = False, color: str = NORMAL) -> QTableWidgetItem:
    """A table cell with the given text, alignment and colour."""
    item = QTableWidgetItem(str(text))
    if center:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    else:
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    item.setForeground(QColor(color))
    return item


def clear_previous_student_data(lms_changed: bool, portal_changed: bool) -> None:
    """
    Delete the saved data of the previous student.
    Only the parts that belong to the changed login are deleted.
    """
    assessments.ensure_table()
    with db.connection() as conn:
        if lms_changed:
            conn.execute("DELETE FROM deadlines")
            conn.execute("DELETE FROM sync_status WHERE source = 'lms'")
        if portal_changed:
            conn.execute("DELETE FROM attendance")
            conn.execute("DELETE FROM course_assessments")
            conn.execute("DELETE FROM course_checked")
            conn.execute("DELETE FROM sync_status WHERE source = 'portal'")


# ---------- Background workers ----------

class SyncWorker(QThread):
    """Runs the full sync in a background thread and reports back when done."""

    finished_with = pyqtSignal(list)    # list of short result lines

    def run(self):
        messages = []

        # 1. LMS + portal (attendance and marks) into the database
        try:
            for result in sync.sync_all():
                mark = "OK" if result.ok else "FAIL"
                messages.append(f"[{mark}] {result.source}: {result.message}")
        except Exception as error:
            messages.append(f"[FAIL] sync: {error}")

        # 2. Calendar file for Thunderbird / Gmail import
        try:
            reminders.export_ics()
            messages.append("[OK] calendar file updated")
        except Exception as error:
            messages.append(f"[FAIL] calendar file: {error}")

        # 3. Google Calendar is OPTIONAL. It only runs if google_credentials.json exists.
        if not gcal_sync.CREDENTIALS_PATH.exists():
            messages.append("[SKIP] Google Calendar: not set up (optional)")
        else:
            try:
                total = gcal_sync.sync_to_google()
                messages.append(f"[OK] Google Calendar: {total} deadline(s) up to date")
            except Exception as error:
                messages.append(f"[FAIL] Google Calendar: {error}")

        self.finished_with.emit(messages)


class SemesterWorker(QThread):
    """Loads one semester's assignments from the LMS, in the background."""

    done = pyqtSignal(object, str)      # (list of assignments or None, error text)

    def __init__(self, semester):
        super().__init__()
        self.semester = semester

    def run(self):
        username, password = credentials.load_credentials("lms")
        if username is None:
            self.done.emit(None, "No LMS login saved yet. Click Logins at the top.")
            return
        try:
            client = LMSClient(username, password)
            client.login()
            items = client.get_semester_assignments(self.semester.start, self.semester.end)
            self.done.emit(items, "")
        except Exception as error:
            self.done.emit(None, str(error))


# ---------- Course marks popup ----------

class AssessmentDialog(QDialog):
    """Popup with every mark (Quiz, Mid term, Final...) of one course."""

    def __init__(self, course_id: str, title: str, items: list[dict], checked_at: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{course_id} - Assessments")
        self.setMinimumSize(660, 440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        background = GradientWidget()
        outer.addWidget(background)

        layout = QVBoxLayout(background)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        # ----- header: course ID and full course name -----
        heading_text = f"{course_id}  •  {title}" if title else course_id
        heading = QLabel(heading_text)
        heading.setObjectName("appTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        subtitle = QLabel("Assessments and marks")
        subtitle.setObjectName("appSub")
        layout.addWidget(subtitle)

        # ----- summary cards -----
        obtained, total, percent = course_summary(items)

        card1, value1 = make_stat("Marks obtained")
        value1.setText(f"{fmt(obtained)} / {fmt(total)}" if total else "-")

        card2, value2 = make_stat("Percentage")
        if percent is not None:
            value2.setText(f"{percent}%")
            value2.setStyleSheet(f"color: {marks_color(percent)};")

        stats = QHBoxLayout()
        stats.addWidget(card1)
        stats.addWidget(card2)
        layout.addLayout(stats)

        # ----- the marks table, or a note if there are none -----
        if items:
            table = make_table(
                ["Name", "Total Marks", "Obtained Marks", "Assigned Date"],
                center_cols=(1, 2, 3),
            )
            table.setRowCount(len(items))
            for row, item in enumerate(items):
                values = [item["name"], item["total"], item["obtained"], item["assigned"]]
                for col, value in enumerate(values):
                    table.setItem(row, col, make_item(value, center=(col > 0)))
            layout.addWidget(table, 1)
        else:
            empty = QLabel("No assessments yet for this course.")
            empty.setObjectName("appSub")
            layout.addWidget(empty)
            layout.addStretch(1)

        last = QLabel(f"Last checked: {pretty_time(checked_at) if checked_at else 'Not checked yet'}")
        last.setObjectName("footer")
        layout.addWidget(last)

        # ----- close button -----
        close_button = QPushButton("Close")
        close_button.setObjectName("accent")
        close_button.setMinimumWidth(110)
        close_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)


# ---------- Logins dialog ----------

class AccountDialog(QDialog):
    """Lets any student type their own LMS and portal ID and password."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("UMT Companion - Logins")
        self.setMinimumWidth(500)

        # Show the saved IDs (never the saved passwords)
        saved_lms = credentials.load_credentials("lms")[0] or ""
        saved_portal = credentials.load_credentials("portal")[0] or ""

        self.lms_user = QLineEdit()
        self.lms_user.setPlaceholderText(saved_lms or "LMS student ID")
        self.lms_pass = QLineEdit()
        self.lms_pass.setPlaceholderText("Password")
        self.lms_pass.setEchoMode(QLineEdit.EchoMode.Password)

        self.portal_user = QLineEdit()
        self.portal_user.setPlaceholderText(saved_portal or "Portal student ID")
        self.portal_pass = QLineEdit()
        self.portal_pass.setPlaceholderText("Password")
        self.portal_pass.setEchoMode(QLineEdit.EchoMode.Password)

        # The dialog uses the same gradient background as the main window
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        background = GradientWidget()
        outer.addWidget(background)

        layout = QVBoxLayout(background)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        # ----- header -----
        title = QLabel("Logins")
        title.setObjectName("appTitle")
        subtitle = QLabel("Your student ID and password for each site")
        subtitle.setObjectName("appSub")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # ----- one card per site -----
        layout.addWidget(self._site_card("LMS", self.lms_user, self.lms_pass))
        layout.addWidget(self._site_card("Student Portal", self.portal_user, self.portal_pass))

        # ----- note -----
        note = QLabel(
            "Passwords are saved in Windows Credential Manager, never in a file. "
            "For each site, fill BOTH ID and password to save it. "
            "Leave both empty to keep what is saved."
        )
        note.setObjectName("appSub")
        note.setWordWrap(True)
        layout.addWidget(note)

        # ----- buttons -----
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)

        save_button = QPushButton("Save")
        save_button.setObjectName("accent")
        save_button.setMinimumWidth(110)
        save_button.clicked.connect(self.save)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)

    @staticmethod
    def _site_card(title_text: str, user_box: QLineEdit, pass_box: QLineEdit) -> QFrame:
        """A rounded card holding the ID and password fields for one site."""
        card = QFrame()
        card.setObjectName("card")

        title = QLabel(title_text)
        title.setObjectName("sectionTitle")

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Student ID", user_box)
        form.addRow("Password", pass_box)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addLayout(form)
        return card

    @staticmethod
    def _is_different_student(site: str, user_box: QLineEdit, pass_box: QLineEdit) -> bool:
        """
        True if the user is filling in a DIFFERENT student ID for this site
        than the one already saved. Ignores capital letters.
        """
        new_user = user_box.text().strip()
        new_pass = pass_box.text()
        old_user = credentials.load_credentials(site)[0]

        # Nothing new typed, or nothing saved before -> no switch
        if not new_user or not new_pass or not old_user:
            return False
        return new_user.lower() != old_user.lower()

    def save(self):
        """Check the fields, ask if a different student is being saved, then save."""
        sites = [
            ("lms", "LMS", self.lms_user, self.lms_pass),
            ("portal", "Portal", self.portal_user, self.portal_pass),
        ]

        # First check everything, so nothing is half-saved
        for site, label, user_box, pass_box in sites:
            user = user_box.text().strip()
            password = pass_box.text()
            if bool(user) != bool(password):
                QMessageBox.warning(
                    self, "Logins",
                    f"For {label}, fill both the ID and the password, or leave both empty.",
                )
                return

        lms_changed = self._is_different_student("lms", self.lms_user, self.lms_pass)
        portal_changed = self._is_different_student("portal", self.portal_user, self.portal_pass)

        # Ask before deleting anything
        if lms_changed or portal_changed:
            answer = QMessageBox.question(
                self,
                "Different student",
                "You are changing to a different student ID.\n\n"
                "The saved deadlines, attendance and marks of the previous student "
                "will be deleted. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        for site, label, user_box, pass_box in sites:
            user = user_box.text().strip()
            password = pass_box.text()
            if user and password:
                credentials.save_credentials(site, user, password)

        if lms_changed or portal_changed:
            clear_previous_student_data(lms_changed, portal_changed)

        self.accept()


# ---------- Main window ----------

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("UMT Companion")
        self.resize(1080, 700)
        self.setStyleSheet(APP_STYLE)
        self.worker = None
        self.sem_worker = None
        self.sem_name = ""
        self.dot_count = 0
        self.fade_anim = None

        db.init_db()
        assessments.ensure_table()

        # ----- header: title + status on the left, buttons on the right -----
        title = QLabel("UMT Companion")
        title.setObjectName("appTitle")
        self.status_label = QLabel("")
        self.status_label.setObjectName("appSub")

        header_text = QVBoxLayout()
        header_text.addWidget(title)
        header_text.addWidget(self.status_label)

        self.logins_button = QPushButton("Logins")
        self.logins_button.clicked.connect(self.open_logins)

        self.sync_button = QPushButton("Sync Now")
        self.sync_button.setObjectName("accent")
        self.sync_button.setMinimumWidth(130)
        self.sync_button.clicked.connect(self.start_sync)

        top_bar = QHBoxLayout()
        top_bar.addLayout(header_text, 1)
        top_bar.addWidget(self.logins_button)
        top_bar.addWidget(self.sync_button)

        # Animates the "Syncing..." text on the button
        self.dot_timer = QTimer(self)
        self.dot_timer.timeout.connect(self._tick_dots)

        # ----- tabs -----
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_deadlines_tab(), "Deadlines")
        self.tabs.addTab(self._build_attendance_tab(), "Attendance")
        self.tabs.addTab(self._build_assessments_tab(), "Assessments")
        self.tabs.addTab(self._build_semester_tab(), "Semester report")
        self.tabs.addTab(self._build_settings_tab(), "Settings")

        # ----- footer -----
        footer = QLabel(f"{DEVELOPER}   •   v{APP_VERSION}")
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignmentFlag.AlignRight)

        # ----- put it together -----
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 20, 24, 14)
        layout.setSpacing(14)
        layout.addLayout(top_bar)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(footer)

        central = GradientWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        # Watch every click in the app, so clicks outside a table clear its selection
        QApplication.instance().installEventFilter(self)

        # Reload the tables every minute, so new data appears on its own
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_all)
        self.timer.start(REFRESH_SECONDS * 1000)

        self.refresh_all()

    # ===== clicks and animation =====

    def _tables(self) -> list:
        """All the data tables in the window."""
        names = ("deadline_table", "attendance_table", "assess_table", "sem_table")
        return [getattr(self, name) for name in names if hasattr(self, name)]

    def eventFilter(self, obj, event):
        """
        Any mouse click that is NOT on a table (or inside one) clears
        the selection of every table.
        """
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget):
            for table in self._tables():
                if obj is table or table.isAncestorOf(obj):
                    return super().eventFilter(obj, event)
            for table in self._tables():
                table.clear_selection_now()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        """Fade the window in every time it appears (startup, or from the tray)."""
        super().showEvent(event)
        self.setWindowOpacity(0.0)
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade_anim.setDuration(FADE_MS)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()

    def _tick_dots(self):
        """Makes the button say Syncing. Syncing.. Syncing... in turn."""
        self.dot_count = (self.dot_count + 1) % 4
        self.sync_button.setText("Syncing" + "." * self.dot_count)

    # ===== building the tabs =====

    def _build_deadlines_tab(self) -> QWidget:
        self.deadline_table = make_table(
            ["Due", "Time left", "Title", "Course", "Type"],
            center_cols=(0, 1),
        )

        card1, self.stat_upcoming = make_stat("Upcoming")
        card2, self.stat_urgent = make_stat(f"Due in {URGENT_HOURS} hours")
        card3, self.stat_overdue = make_stat("Overdue")

        stats = QHBoxLayout()
        stats.addWidget(card1)
        stats.addWidget(card2)
        stats.addWidget(card3)

        layout = QVBoxLayout()
        layout.addLayout(stats)
        layout.addWidget(self.deadline_table, 1)

        page = QWidget()
        page.setLayout(layout)
        return page

    def _build_attendance_tab(self) -> QWidget:
        self.attendance_table = make_table(
            ["Course", "Title", "Attended", "Absent", "%", "Updated"],
            center_cols=(2, 3, 4, 5),
        )
        self.low_label = QLabel("")

        card1, self.stat_overall = make_stat("Overall attendance")
        card2, self.stat_subjects = make_stat("Subjects")
        card3, self.stat_low = make_stat(f"Below {LOW_ATTENDANCE:.0f}%")

        stats = QHBoxLayout()
        stats.addWidget(card1)
        stats.addWidget(card2)
        stats.addWidget(card3)

        self.legend_label = QLabel(
            f'<span style="color:{GREEN}">■ 80% or more</span>&nbsp;&nbsp;'
            f'<span style="color:{RED}">■ below 80%</span>'
            "&nbsp;&nbsp;&nbsp;&nbsp;Absent: "
            f'<span style="color:{GREEN}">■ 0</span>&nbsp;&nbsp;'
            f'<span style="color:{RED}">■ 1 or more</span>'
        )

        layout = QVBoxLayout()
        layout.addLayout(stats)
        layout.addWidget(self.low_label)
        layout.addWidget(self.legend_label)
        layout.addWidget(self.attendance_table, 1)

        page = QWidget()
        page.setLayout(layout)
        return page

    def _build_assessments_tab(self) -> QWidget:
        self.assess_table = make_table(
            ["Course ID", "Course name", "Last checked"],
            center_cols=(2,),
        )
        self.assess_table.cellClicked.connect(self.open_course_assessments)

        # Filled in by load_assessments()
        self._assess_rows = []
        self._assess_titles = {}

        self.assess_summary = QLabel("")
        self.assess_summary.setObjectName("appSub")

        hint = QLabel("Click a course to see all its marks (Quiz, Mid term, Final...)")
        hint.setObjectName("appSub")

        layout = QVBoxLayout()
        layout.addWidget(self.assess_summary)
        layout.addWidget(hint)
        layout.addWidget(self.assess_table, 1)

        page = QWidget()
        page.setLayout(layout)
        return page

    def _build_semester_tab(self) -> QWidget:
        self.sem_combo = QComboBox()
        self.sem_combo.addItems(semester_choices())

        self.sem_button = QPushButton("Load report")
        self.sem_button.setObjectName("accent")
        self.sem_button.clicked.connect(self.load_semester)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Semester:"))
        controls.addWidget(self.sem_combo)
        controls.addWidget(self.sem_button)
        controls.addStretch(1)

        self.sem_summary = QLabel(
            "Choose a semester and click Load report. It checks every course, so it can take a minute."
        )
        self.sem_summary.setObjectName("appSub")
        self.sem_table = make_table(
            ["Status", "Due", "Title", "Course", "Grade"],
            center_cols=(0, 1, 4),
        )

        layout = QVBoxLayout()
        layout.addLayout(controls)
        layout.addWidget(self.sem_summary)
        layout.addWidget(self.sem_table, 1)

        page = QWidget()
        page.setLayout(layout)
        return page

    def _build_settings_tab(self) -> QWidget:
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Sync results will appear here.")

        open_data_button = QPushButton("Open data folder")
        open_data_button.clicked.connect(lambda: self._open_folder(db.APP_FOLDER))

        open_calendar_button = QPushButton("Open calendar folder")
        open_calendar_button.clicked.connect(lambda: self._open_folder(reminders.ICS_FOLDER))

        buttons = QHBoxLayout()
        buttons.addWidget(open_data_button)
        buttons.addWidget(open_calendar_button)
        buttons.addStretch(1)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Sync log:"))
        layout.addWidget(self.log, 1)
        layout.addLayout(buttons)

        page = QWidget()
        page.setLayout(layout)
        return page

    # ===== reading the database =====

    def refresh_all(self):
        self.load_deadlines()
        self.load_attendance()
        self.load_assessments()
        if not self._is_syncing():
            self.load_status()

    def load_deadlines(self):
        now = datetime.now()
        items = db.get_deadlines()
        self.deadline_table.setRowCount(len(items))

        upcoming = urgent = overdue = 0
        for row, item in enumerate(items):
            due = item["due"]
            if due < now:
                overdue += 1
            else:
                upcoming += 1
                if (due - now).total_seconds() < URGENT_HOURS * 3600:
                    urgent += 1

            # red = overdue, orange = due within 24 hours
            if due < now:
                colour = RED
            elif (due - now).total_seconds() < URGENT_HOURS * 3600:
                colour = ORANGE
            else:
                colour = NORMAL

            values = [
                due.strftime(TIME_FORMAT),
                time_left_text(due, now),
                item["title"],
                item["course"],
                ACTIVITY_NAMES.get(item["activity_type"], item["activity_type"]),
            ]
            for col, value in enumerate(values):
                self.deadline_table.setItem(
                    row, col, make_item(value, center=(col in (0, 1)), color=colour)
                )

        self.stat_upcoming.setText(str(upcoming))
        self.stat_urgent.setText(str(urgent))
        self.stat_overdue.setText(str(overdue))
        self.stat_overdue.setStyleSheet(f"color: {RED};" if overdue else "")
        self.stat_urgent.setStyleSheet(f"color: {ORANGE};" if urgent else "")

    def load_attendance(self):
        rows = db.get_attendance()
        self.attendance_table.setRowCount(len(rows))
        low_count = 0
        total_attended = total_lectures = 0

        for row, subject in enumerate(rows):
            total = subject["total"]
            attended = subject["attended"]
            absent = total - attended
            percent = round(attended / total * 100, 1) if total else 0.0
            if percent < LOW_ATTENDANCE:
                low_count += 1
            total_attended += attended
            total_lectures += total

            values = [
                subject["course_id"],
                subject["title"],
                f"{attended}/{total}",
                absent,
                f"{percent}%",
                pretty_time(subject["updated_at"]),
            ]
            for col, value in enumerate(values):
                if col in (2, 4):              # Attended and % -> red below 80%, else green
                    colour = attendance_color(percent)
                elif col == 3:                 # Absent -> red if any, else green
                    colour = absent_color(absent)
                elif col == 0:
                    colour = BLUE
                else:                          # Title, Updated -> normal text
                    colour = NORMAL
                self.attendance_table.setItem(
                    row, col, make_item(value, center=(col >= 2), color=colour)
                )

        overall = round(total_attended / total_lectures * 100, 1) if total_lectures else 0.0
        self.stat_overall.setText(f"{overall}%")
        self.stat_overall.setStyleSheet(f"color: {attendance_color(overall)};" if total_lectures else "")
        self.stat_subjects.setText(str(len(rows)))
        self.stat_low.setText(str(low_count))
        self.stat_low.setStyleSheet(f"color: {RED};" if low_count else "")

        if low_count:
            self.low_label.setText(f"Warning: {low_count} subject(s) below {LOW_ATTENDANCE:.0f}%")
            self.low_label.setStyleSheet(f"color: {RED}; font-weight: bold;")
        else:
            self.low_label.setText("")

    def load_assessments(self):
        saved = assessments.load_all()
        titles = {s["course_id"]: s["title"] for s in db.get_attendance()}
        self._assess_titles = titles

        # Every course we know about, even if it was never checked yet
        course_ids = sorted(set(titles) | set(saved))
        self._assess_rows = course_ids
        self.assess_table.setRowCount(len(course_ids))

        for row, course_id in enumerate(course_ids):
            entry = saved.get(course_id, {"items": [], "updated_at": ""})

            if entry["updated_at"]:
                checked_text = pretty_time(entry["updated_at"])
                checked_colour = SOFT_BLUE
            else:
                checked_text = "Not checked yet"
                checked_colour = DIM

            self.assess_table.setItem(row, 0, make_item(course_id, color=BLUE))
            self.assess_table.setItem(row, 1, make_item(titles.get(course_id, ""), color=SOFT_BLUE))
            self.assess_table.setItem(
                row, 2, make_item(checked_text, center=True, color=checked_colour)
            )

        if course_ids:
            self.assess_summary.setText(
                f"{len(course_ids)} course(s). Marks update on Sync Now."
            )
        else:
            self.assess_summary.setText("No courses yet. Click Sync Now.")

    def open_course_assessments(self, row: int, column: int):
        """Open the marks popup for the course that was clicked."""
        if row < 0 or row >= len(self._assess_rows):
            return
        course_id = self._assess_rows[row]
        entry = assessments.load_all().get(course_id, {"items": [], "updated_at": ""})
        dialog = AssessmentDialog(
            course_id,
            self._assess_titles.get(course_id, ""),
            entry["items"],
            entry["updated_at"],
            self,
        )
        dialog.exec()

    def load_status(self):
        parts = []

        # New users see this until they save their logins
        if credentials.load_credentials("lms")[0] is None:
            parts.append("Set up your logins (click Logins)")

        for source, name in (("lms", "LMS"), ("portal", "Portal")):
            status = db.get_sync_status(source)
            if status is None:
                parts.append(f"{name}: never synced")
            elif status["last_error"]:
                parts.append(
                    f"{name}: last try failed (showing data from {pretty_time(status['last_success'])})"
                )
            else:
                parts.append(f"{name}: synced at {pretty_time(status['last_success'])}")
        self.status_label.setText("   •   ".join(parts))

    # ===== logins =====

    def open_logins(self):
        dialog = AccountDialog(self)
        if dialog.exec():
            QMessageBox.information(self, "Logins", "Saved. Click Sync Now to load your data.")
            self.refresh_all()

    # ===== sync =====

    def _is_syncing(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def start_sync(self):
        if self._is_syncing():
            return
        self.sync_button.setEnabled(False)
        self.dot_count = 0
        self.sync_button.setText("Syncing")
        self.dot_timer.start(400)
        self.status_label.setText("Fetching fresh data in the background, this can take a few minutes")

        self.worker = SyncWorker()
        self.worker.finished_with.connect(self.on_sync_done)
        self.worker.start()

    def on_sync_done(self, messages: list):
        self.dot_timer.stop()
        self.sync_button.setText("Sync Now")
        self.sync_button.setEnabled(True)

        self.log.append(f"--- {datetime.now().strftime(TIME_FORMAT)} ---")
        for line in messages:
            self.log.append(line)
        self.log.append("")

        self.refresh_all()

    # ===== semester report =====

    def load_semester(self):
        if self.sem_worker is not None and self.sem_worker.isRunning():
            return

        choice = self.sem_combo.currentText()
        if choice == "Current semester":
            semester = current_semester()
            if semester is None:
                self.sem_summary.setText(
                    "Today is in the break (26 Jul to 30 Sep). Pick a semester from the list."
                )
                return
        else:
            semester = parse_semester_name(choice)

        self.sem_name = semester.name
        self.sem_button.setEnabled(False)
        self.sem_table.setRowCount(0)
        self.sem_summary.setText(f"Loading {semester.name}... please wait")

        self.sem_worker = SemesterWorker(semester)
        self.sem_worker.done.connect(self.on_semester_done)
        self.sem_worker.start()

    def on_semester_done(self, items, error):
        self.sem_button.setEnabled(True)

        if error:
            self.sem_summary.setText(f"Could not load: {error}")
            return

        if not items:
            self.sem_summary.setText(f"No assignments with a due date in {self.sem_name}.")
            return

        now = datetime.now()
        done = overdue = pending = 0
        self.sem_table.setRowCount(len(items))

        for row, a in enumerate(items):
            if a.submitted:
                label, color = "DONE", GREEN
                done += 1
            elif a.due < now:
                label, color = "OVERDUE", RED
                overdue += 1
            else:
                label, color = "PENDING", ORANGE
                pending += 1

            values = [
                label,
                a.due.strftime(TIME_FORMAT),
                a.title,
                a.course,
                a.grade,
            ]
            for col, value in enumerate(values):
                self.sem_table.setItem(
                    row, col,
                    make_item(value, center=(col in (0, 1, 4)), color=color if col == 0 else NORMAL),
                )

        self.sem_summary.setText(
            f"{self.sem_name}:   Total {len(items)}   "
            f"Done {done}   Overdue {overdue}   Pending {pending}"
        )

    # ===== small helpers =====

    def _open_folder(self, folder):
        """Open a folder in File Explorer (Windows only)."""
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def closeEvent(self, event):
        """Closing the window only HIDES it. The app keeps running in the tray."""
        event.ignore()
        self.hide()


# Run this file directly to see the window:  python src\gui.py
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())