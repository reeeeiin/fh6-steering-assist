@echo off
rem То же, что run.bat, но с покадровым CSV-логом контура.
rem Переменную ставим ПОСЛЕ повышения прав: при UAC-элевации окружение
rem родительского процесса не наследуется, и set из внешней консоли теряется.
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
