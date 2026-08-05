@echo off
cd /d "%~dp0"
python forza_assist_lite.py
if errorlevel 1 pause
