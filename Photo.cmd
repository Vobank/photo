@echo off
setlocal
chcp 65001 >nul
set "PHOTO_EXE=%~dp0backend\.venv\Scripts\photo.exe"
if not exist "%PHOTO_EXE%" (
    echo Photo is not installed yet. Double-click install.cmd first.
    pause
    exit /b 1
)
"%PHOTO_EXE%" serve --open %*
if errorlevel 1 pause
