# UMT Companion

An unofficial Windows desktop app for UMT students that syncs
LMS deadlines and Student Portal attendance, and sends reminders.

> ⚠️ This is an unofficial, personal project. It is not affiliated
> with or endorsed by the University of Management and Technology.
> Use it only with your own account.

## Status
🚧 Work in progress

## Planned features
- Auto-login to UMT LMS and Student Portal
- Sync assignment/project deadlines
- Per-subject attendance
- Windows notifications + .ics calendar export
- Simple GUI with system tray

## Security
Your password is stored in Windows Credential Manager (via `keyring`),
never in plain text and never in this repository.

## Setup (for developers)
1. Install Python 3
2. `python -m venv venv`
3. `venv\Scripts\activate`
4. `pip install -r requirements.txt`