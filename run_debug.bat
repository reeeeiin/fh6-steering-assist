@echo off
rem Same as run.bat, but with the frame-by-frame CSV log enabled.
rem The variable is set AFTER elevation: a UAC-elevated process does
rem not inherit the caller's environment, so an outer set is lost.
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set ASSIST_DEBUG_LOG=1
echo === DEBUG LOG ON ===
echo Log will be written on exit to:
echo   %APPDATA%\ForzaAssistLite\assist_log.csv
echo.
python forza_assist_lite.py
if errorlevel 1 pause
