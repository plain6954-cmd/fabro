@echo off
title FABRO Local Server
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_local_background.ps1"
if errorlevel 1 pause
