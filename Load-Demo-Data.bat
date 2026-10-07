@echo off
REM Multi Agentic Company - load the demo data (projects, tasks, approvals) for a client demo
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\demo.ps1" load
