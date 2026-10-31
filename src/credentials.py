"""
credentials.py

Securely save and load login details using Windows Credential Manager
(through the `keyring` library).

The password is NEVER written to any file inside this project,
so it can never be uploaded to GitHub by mistake.
"""

import keyring
from keyring.errors import PasswordDeleteError

# All our entries will appear under this name in Windows Credential Manager.
SERVICE_NAME = "UMT Companion"


def save_credentials(site: str, username: str, password: str) -> None:
    """
    Save the username and password for one website.

    `site` is a short label, e.g. "lms" or "portal", so we can store
    separate logins for the LMS and the Student Portal.
    """
    # keyring stores (service, key) -> secret value, in Windows' own encrypted vault
    keyring.set_password(SERVICE_NAME, f"{site}_username", username)
    keyring.set_password(SERVICE_NAME, f"{site}_password", password)


def load_credentials(site: str):
    """
    Return (username, password) for a site.
    If nothing is saved yet, return (None, None).
    """
    username = keyring.get_password(SERVICE_NAME, f"{site}_username")
    password = keyring.get_password(SERVICE_NAME, f"{site}_password")

    # Only return them if BOTH exist; half-saved data is treated as "nothing saved"
    if username and password:
        return username, password
    return None, None


def delete_credentials(site: str) -> None:
    """Remove the saved username and password for a site (e.g. after a wrong password)."""
    for key in (f"{site}_username", f"{site}_password"):
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except PasswordDeleteError:
            # Nothing was saved under this key, which is fine
            pass