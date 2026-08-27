@echo off
rem Walks the loading and first launch screens without installing anything.
rem No drivers are touched, so this does not need administrator rights.
rem
rem   run_boot_demo.bat          full run: loading -> 5 steps -> done -> app
rem   run_boot_demo.bat 3        stops on step 3
rem   run_boot_demo.bat 3 hide   stops on step 3 and shows the error panel
rem                              (failed, noadmin, reboot, hide, vigem)
cd /d "%~dp0"
if "%~1"=="" (set ASSIST_BOOT_DEMO=1) else (set ASSIST_BOOT_DEMO=%~1)
set ASSIST_BOOT_ERROR=%~2
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
pause
exit /b 1
:gotpy

%PY% forza_assist_lite.py
