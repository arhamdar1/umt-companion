"""
phase2_test.py

Test for Phase 2:
- First run: asks for your LMS username/password and saves them securely.
- Next runs: uses the saved ones automatically (no typing).

Run with:        python src\\phase2_test.py
Reset saved login: python src\\phase2_test.py --reset
"""

import sys
from getpass import getpass   # reads the password without showing it on screen

from credentials import save_credentials, load_credentials, delete_credentials
from lms_client import LMSClient, LoginError, LMSConnectionError

SITE = "lms"   # label under which LMS login is stored


def ask_and_save():
    """Ask the user for their login and store it in Windows Credential Manager."""
    username = input("LMS username: ").strip()
    password = getpass("LMS password (hidden while typing): ")
    save_credentials(SITE, username, password)
    print("[OK] Saved securely in Windows Credential Manager.")
    return username, password


def main():
    # Optional: "--reset" deletes the saved login so you can enter it again
    if "--reset" in sys.argv:
        delete_credentials(SITE)
        print("[OK] Saved LMS login deleted.")
        return

    username, password = load_credentials(SITE)

    if username is None:
        print("No saved LMS login found.")
        username, password = ask_and_save()
    else:
        print(f"Using saved login for: {username}")

    client = LMSClient(username, password)

    try:
        client.login()
        print("[OK] LMS login successful!")

    except LoginError as error:
        print(f"[FAIL] Login rejected: {error}")
        # Don't keep a wrong password saved
        delete_credentials(SITE)
        print("Saved login removed. Run the script again to re-enter it.")

    except LMSConnectionError as error:
        print(f"[NETWORK] {error}")


# This makes main() run only when you run this file directly
if __name__ == "__main__":
    main()