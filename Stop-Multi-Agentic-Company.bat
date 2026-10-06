@echo off
REM Multi Agentic Company - stop all services (your data is kept)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\stop.ps1"
