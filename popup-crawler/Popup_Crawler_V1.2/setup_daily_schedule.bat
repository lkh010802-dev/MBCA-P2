@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "RUN_TIME=08:00"
if not "%~1"=="" set "RUN_TIME=%~1"

echo ========================================
echo Popup Crawler v1.0.0 Schedule Setup

echo ========================================
echo Daily time: %RUN_TIME%
echo Task name : PopupCrawlerDaily
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [SETUP REQUIRED] Run setup.bat first.
  pause
  exit /b 2
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_daily_schedule.ps1" -TaskName "PopupCrawlerDaily" -Time "%RUN_TIME%"
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
  echo [SUCCESS] Daily schedule registration completed.
  echo Use check_daily_schedule.bat to verify it.
) else (
  echo [FAILED] Schedule registration failed. exit_code=%EXITCODE%
)
echo.
pause
exit /b %EXITCODE%
