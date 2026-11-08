@echo off
rem Double-click entry point: runs install.ps1 without changing the system execution policy.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "CODE=%ERRORLEVEL%"
echo.
pause
exit /b %CODE%
