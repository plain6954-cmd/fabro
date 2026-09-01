@echo off
title FABRO Local Server
powershell.exe -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\start_local.ps1"
