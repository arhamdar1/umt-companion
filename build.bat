@echo off
echo Building UMT Companion.exe ...
echo.

pyinstaller --noconsole --onefile --noconfirm --clean --name "UMT Companion" --collect-all playwright src\app.py

echo.
echo Done. The exe is in the dist folder.
pause