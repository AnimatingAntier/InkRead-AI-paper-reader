@echo off
setlocal
cd /d "%~dp0"
set "POWERSHELL=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not exist "%POWERSHELL%" set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-inkread.ps1" %*
if errorlevel 1 pause
