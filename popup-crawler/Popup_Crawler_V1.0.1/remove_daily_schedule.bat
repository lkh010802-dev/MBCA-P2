@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo Popup Crawler v1.0.0 Schedule Remove

echo ========================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\remove_daily_schedule.ps1" -TaskName "PopupCrawlerDaily"
set "EXITCODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXITCODE%
