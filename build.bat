@echo off
cd /d "%~dp0"
echo === Building Forza Assist Lite (single exe) ===
echo.

python -m pip install pyinstaller vgamepad pywebview
if errorlevel 1 goto fail

set EXTRA=
if exist Oswald-Medium.ttf set EXTRA=%EXTRA% --add-data "Oswald-Medium.ttf;."
if exist Oswald-Regular.ttf set EXTRA=%EXTRA% --add-data "Oswald-Regular.ttf;."
if exist assets set EXTRA=%EXTRA% --add-data "assets;assets"
if exist app.ico set EXTRA=%EXTRA% --icon app.ico

python -m PyInstaller --onefile --noconsole --uac-admin --name SteeringAssist --collect-all vgamepad --collect-all webview %EXTRA% forza_assist_lite.py
if errorlevel 1 goto fail

echo.
echo === DONE ===
echo Result: dist\SteeringAssist.exe
pause
exit /b 0

:fail
echo.
echo === BUILD FAILED - see error text above ===
pause
exit /b 1
