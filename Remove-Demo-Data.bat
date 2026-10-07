@echo off
REM Multi Agentic Company - remove the demo data again (your own projects are not touched)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\demo.ps1" remove
