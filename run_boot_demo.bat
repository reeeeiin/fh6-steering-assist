@echo off
setlocal enabledelayedexpansion
rem Walks the loading and setup screens without installing anything, without
rem touching a driver or the pad, and without restarting the machine - the
rem Restart button raises its notice and counts down, but orders nothing.
rem No administrator rights needed.
rem
rem   run_boot_demo.bat            pick a scenario from the menu
rem   run_boot_demo.bat 3          straight to: stops on step 3
rem   run_boot_demo.bat 4 reboot   stops on step 4 and shows the restart panel
rem                                (failed, noadmin, reboot, hide, vigem)
cd /d "%~dp0"

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

if not "%~1"=="" (
  set ASSIST_BOOT_DEMO=%~1
  set ASSIST_BOOT_ERROR=%~2
  set ASSIST_BOOT_REPEAT=
  goto run
)

:menu
cls
echo.
echo   Steering Assist - setup walkthrough
echo   ==================================
echo.
echo   Nothing is installed, no driver is touched, and the machine is
echo   never restarted.
echo.
echo     1  First launch           five steps at the pace of real work
echo     2  Repeat launch          the same five as checks, quickly
echo     3  Waiting for a restart  stops on step 4 with the prompt, and
echo                               the notice its button raises
echo     4  Install failed         the error panel
echo     5  No admin rights        the error panel
echo     6  Pad hiding failed      the error panel
echo     7  Virtual pad missing    the error panel
echo     8  Stop on a step         asks which
echo     0  Quit
echo.
set "pick="
set /p "pick=  Choose: "

set ASSIST_BOOT_DEMO=1
set ASSIST_BOOT_ERROR=
set ASSIST_BOOT_REPEAT=

if "!pick!"=="0" exit /b 0
if "!pick!"=="1" goto run
if "!pick!"=="2" (set ASSIST_BOOT_REPEAT=1& goto run)
if "!pick!"=="3" (set ASSIST_BOOT_DEMO=4& set ASSIST_BOOT_ERROR=reboot& goto run)
if "!pick!"=="4" (set ASSIST_BOOT_DEMO=2& set ASSIST_BOOT_ERROR=failed& goto run)
if "!pick!"=="5" (set ASSIST_BOOT_DEMO=2& set ASSIST_BOOT_ERROR=noadmin& goto run)
if "!pick!"=="6" (set ASSIST_BOOT_DEMO=3& set ASSIST_BOOT_ERROR=hide& goto run)
if "!pick!"=="7" (set ASSIST_BOOT_DEMO=4& set ASSIST_BOOT_ERROR=vigem& goto run)
if "!pick!"=="8" goto onestep
goto menu

:onestep
echo.
set "step="
set /p "step=  Which step, 1-5: "
if "!step!"=="" goto menu
set ASSIST_BOOT_DEMO=!step!
goto run

:run
echo.
if "!ASSIST_BOOT_REPEAT!"=="1" (
  echo   Repeat launch - the steps are checks, and quick
) else if "!ASSIST_BOOT_ERROR!"=="" (
  echo   Walking to step !ASSIST_BOOT_DEMO!
) else (
  echo   Stopping on step !ASSIST_BOOT_DEMO!, panel "!ASSIST_BOOT_ERROR!"
)
echo   Close the window to come back here.
echo.
%PY% forza_assist_lite.py

if not "%~1"=="" exit /b 0
echo.
set "again="
set /p "again=  Another one? [Y/n]: "
if /i "!again!"=="n" exit /b 0
goto menu
