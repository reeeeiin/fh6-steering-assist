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
python forza_assist_lite.py
