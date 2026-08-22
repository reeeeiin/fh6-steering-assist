@echo off
cd /d "%~dp0"
echo === Building Forza Assist Lite (single exe) ===
echo.

python -m pip install pyinstaller vgamepad pywebview pygame
if errorlevel 1 goto fail

rem The series lives in the script, the build number comes from git, and
rem the two are joined here. build.txt is packed into the exe so a shipped
rem build still knows which one it is with no git on the machine.
set SERIES=
for /f tokens^=2^ delims^=^" %%v in ('findstr /b /c:"APP_SERIES" forza_assist_lite.py') do set SERIES=%%v
if "%SERIES%"=="" set SERIES=0.0
set BUILDID=
for /f %%v in ('python toolsuild_id.py') do set BUILDID=%%v
if "%BUILDID%"=="" set BUILDID=dev
if not exist assets mkdir assets
> assetsuild.txt echo %BUILDID%
set VER=%SERIES%.%BUILDID%
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
if exist assets set EXTRA=%EXTRA% --add-data "assets;assets"
if exist licenses set EXTRA=%EXTRA% --add-data "licenses;licenses"
if exist NOTICE.md set EXTRA=%EXTRA% --add-data "NOTICE.md;."
if exist LICENSE set EXTRA=%EXTRA% --add-data "LICENSE;."
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
