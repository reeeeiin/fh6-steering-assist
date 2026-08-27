@echo off
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
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
if errorlevel 1 pause
