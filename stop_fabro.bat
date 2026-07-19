@echo off
title Stop FABRO Local Server
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_local.ps1"
if errorlevel 1 pause
