"""
lms_client.py

Handles logging into UMT LMS (which runs on Moodle).
Later phases will add methods here to fetch deadlines.
"""

import requests
from bs4 import BeautifulSoup

# Main LMS address and its login page (found during our DevTools recon)
BASE_URL = "https://lms.umt.edu.pk"
LOGIN_URL = f"{BASE_URL}/login/index.php"

# How many seconds to wait for the website before giving up
TIMEOUT_SECONDS = 20


# ---------- Custom errors ----------
# Having our own error types lets the GUI show a clear, specific message later.

class LoginError(Exception):
    """Raised when the LMS rejects the username/password."""


class LMSConnectionError(Exception):
    """Raised when the LMS can't be reached (no internet, site down, timeout)."""


# ---------- The client ----------

class LMSClient:
    """A logged-in 'browser session' with the UMT LMS."""

    def __init__(self, username: str, password: str):
        self.username = username
        self._password = password          # underscore = "private, don't print this"

        # A Session remembers cookies between requests, just like a browser.
        # After login, Moodle gives us a 'MoodleSession' cookie that proves who we are.
        self.session = requests.Session()

        self.logged_in = False

    def login(self) -> None:
        """
        Log into the LMS.
        Raises LMSConnectionError or LoginError if something goes wrong.
        """

        # Step 1: open the login page to get the hidden 'logintoken'
        try:
            response = self.session.get(LOGIN_URL, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()    # turns 404/500 errors into exceptions
        except requests.RequestException as error:
            raise LMSConnectionError(f"Could not open the LMS login page: {error}") from error

        soup = BeautifulSoup(response.text, "html.parser")
        token_input = soup.find("input", {"name": "logintoken"})

        # Step 2: send the login form (same fields we saw in the DevTools Payload tab)
        payload = {
            "anchor": "",
            "logintoken": token_input["value"] if token_input else "",
            "username": self.username,
            "password": self._password,
        }

        try:
            # requests automatically follows Moodle's 303 redirects
            response = self.session.post(LOGIN_URL, data=payload, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as error:
            raise LMSConnectionError(f"Could not send the login form: {error}") from error

        # Step 3: check the result.
        # On success Moodle redirects away from /login/.
        # On failure it keeps us on the login page and shows an error message.
        if "/login/" in response.url:
            soup = BeautifulSoup(response.text, "html.parser")
            error_box = soup.find(id="loginerrormessage") or soup.find(class_="alert-danger")
            message = (
                error_box.get_text(strip=True)
                if error_box
                else "Login failed. Please check your username and password."
            )
            raise LoginError(message)

        self.logged_in = True