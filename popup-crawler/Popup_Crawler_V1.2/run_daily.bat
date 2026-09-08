@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo ========================================
  echo Popup Crawler v1.0.0 Daily Runner
  echo ========================================
  echo.
  echo [SETUP REQUIRED] .venv was not found.
  echo Run setup.bat once, then run this file again.
  echo.
  pause
  exit /b 2
)

echo ========================================
echo Popup Crawler v1.0.0 Daily Runner

echo ========================================
echo.

"%PY%" -u run_daily.py
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
  echo [SUCCESS] Daily crawl/integration completed.
  echo Backend CSV: output\YYYYMMDD_popup.csv
) else (
  echo [BLOCKED/FAILED] Master/CSV was not safely updated.
  echo Check data\daily\latest_summary.txt
)
echo.
pause
exit /b %EXITCODE%
