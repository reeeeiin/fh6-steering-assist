@echo off
cd /d "%~dp0"
echo === Building Forza Assist Lite (single exe) ===
echo.

rem Find an interpreter that actually runs. Installed without "Add
rem python.exe to PATH", that name belongs to a Microsoft Store stub which
rem opens the Store instead of running anything - the py launcher ships
rem either way and points at the real one.
set PY=py -3
%PY% -c "import sys" >nul 2>&1
if not errorlevel 1 goto gotpy
set PY=python
%PY% -c "import sys" >nul 2>&1
if not errorlevel 1 goto gotpy
echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/ and tick
echo "Add python.exe to PATH" in the installer, then run this again.
goto fail
:gotpy

%PY% -m pip install pyinstaller vgamepad pywebview pygame
if errorlevel 1 goto fail

rem The series lives in the script, the build number comes from git, and
rem the two are joined here. build.txt is packed into the exe so a shipped
rem build still knows which one it is with no git on the machine.
set SERIES=
for /f tokens^=2^ delims^=^" %%v in ('findstr /b /c:"APP_SERIES" forza_assist_lite.py') do set SERIES=%%v
if "%SERIES%"=="" set SERIES=0.0
set BUILDID=
for /f %%v in ('%PY% tools\build_id.py') do set BUILDID=%%v
if "%BUILDID%"=="" set BUILDID=dev
if not exist assets mkdir assets
> assets\build.txt echo %BUILDID%
set VER=%SERIES%.%BUILDID%
echo Building version %VER%

rem The UI font is a full CJK family, 26 MB per weight. Subset it to the
rem characters the interface actually uses - about 13 KB each.
%PY% tools\subset_font.py
if errorlevel 1 goto fail

rem Driver installers go INSIDE the exe so the app never needs the
rem network on a user machine. Fetched once, at build time.
%PY% tools\fetch_drivers.py
if errorlevel 1 goto fail

set EXTRA=
if exist drivers set EXTRA=%EXTRA% --add-data "drivers;drivers"
if exist assets set EXTRA=%EXTRA% --add-data "assets;assets"
if exist licenses set EXTRA=%EXTRA% --add-data "licenses;licenses"
if exist NOTICE.md set EXTRA=%EXTRA% --add-data "NOTICE.md;."
if exist LICENSE set EXTRA=%EXTRA% --add-data "LICENSE;."
if exist steering.ico set EXTRA=%EXTRA% --icon steering.ico

%PY% -m PyInstaller --onefile --noconsole --uac-admin --name SteeringAssist-%VER% --collect-all vgamepad --collect-all webview --collect-all pygame %EXTRA% forza_assist_lite.py
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
