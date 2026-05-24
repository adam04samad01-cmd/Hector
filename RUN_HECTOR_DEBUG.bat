@echo off
cd /d "%~dp0"

echo Starting Hector 1.5 debug launcher...
echo Project folder: %CD%
echo.

powershell.exe -NoExit -ExecutionPolicy Bypass -File "%~dp0START_HECTOR_15.ps1"
