@echo off
cd /d "%~dp0"
echo === Building Forza Assist Lite (single exe) ===
echo.

python -m pip install pyinstaller vgamepad pywebview pygame
if errorlevel 1 goto fail

rem Version is read from APP_VERSION in the script - single source of truth
set VER=
for /f tokens^=2^ delims^=^" %%v in ('findstr /b /c:"APP_VERSION" forza_assist_lite.py') do set VER=%%v
if "%VER%"=="" set VER=0.0.0
echo Building version %VER%

rem The UI font is a full CJK family, 26 MB per weight. Subset it to the
rem characters the interface actually uses - about 13 KB each.
python tools\subset_font.py
if errorlevel 1 goto fail

rem Driver installers go INSIDE the exe so the app never needs the
rem network on a user machine. Fetched once, at build time.
python tools\fetch_drivers.py
if errorlevel 1 goto fail

set EXTRA=
if exist drivers set EXTRA=%EXTRA% --add-data "drivers;drivers"
if exist Oswald-Medium.ttf set EXTRA=%EXTRA% --add-data "Oswald-Medium.ttf;."
if exist Oswald-Regular.ttf set EXTRA=%EXTRA% --add-data "Oswald-Regular.ttf;."
if exist assets set EXTRA=%EXTRA% --add-data "assets;assets"
if exist steering.ico set EXTRA=%EXTRA% --icon steering.ico

python -m PyInstaller --onefile --noconsole --uac-admin --name SteeringAssist-%VER% --collect-all vgamepad --collect-all webview --collect-all pygame %EXTRA% forza_assist_lite.py
if errorlevel 1 goto fail

echo.
echo === DONE ===
echo Result: dist\SteeringAssist-%VER%.exe
pause
exit /b 0

:fail
echo.
echo === BUILD FAILED - see error text above ===
pause
exit /b 1
