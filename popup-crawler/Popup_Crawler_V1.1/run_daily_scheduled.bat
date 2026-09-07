@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" exit /b 2

if not exist "logs\scheduler" mkdir "logs\scheduler"
for /f %%I in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
set "LOG=logs\scheduler\%STAMP%.log"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo [%date% %time%] Popup Crawler v1.0.1 scheduled run started.>> "%LOG%"
"%PY%" -u run_daily.py >> "%LOG%" 2>&1
set "EXITCODE=%ERRORLEVEL%"
echo [%date% %time%] Scheduled run finished. exit_code=%EXITCODE%>> "%LOG%"
copy /Y "%LOG%" "logs\scheduler\latest.log" >nul 2>nul

rem Keep scheduler wrapper logs for 30 days. data/daily keeps the application reports.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath 'logs\scheduler' -Filter '*.log' -File ^| Where-Object { $_.Name -ne 'latest.log' -and $_.LastWriteTime -lt (Get-Date).AddDays(-30) } ^| Remove-Item -Force" >nul 2>nul

exit /b %EXITCODE%
