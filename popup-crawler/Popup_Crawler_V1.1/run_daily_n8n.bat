@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
set "REPORT=data\daily\latest_report.json"
set "MARKER=%TEMP%\popup_crawler_n8n_%RANDOM%_%RANDOM%.tmp"

if not exist "%PY%" (
  echo [ERROR] .venv was not found. Run setup.bat first.
  exit /b 2
)

> "%MARKER%" echo started

call "run_daily_scheduled.bat"
set "CRAWLER_EXIT=%ERRORLEVEL%"

if not exist "%REPORT%" (
  echo [ERROR] Daily report was not created.
  if exist "%MARKER%" del /q "%MARKER%" >nul 2>nul
  exit /b %CRAWLER_EXIT%
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$report=Get-Item -LiteralPath '%REPORT%'; $marker=Get-Item -LiteralPath '%MARKER%'; if ($report.LastWriteTimeUtc -lt $marker.LastWriteTimeUtc) { exit 1 } else { exit 0 }" >nul 2>nul
set "REPORT_FRESH=%ERRORLEVEL%"

if exist "%MARKER%" del /q "%MARKER%" >nul 2>nul

if not "%REPORT_FRESH%"=="0" (
  echo [ERROR] Daily report exists but was not updated by this run.
  exit /b %CRAWLER_EXIT%
)

echo crawler_exit_code=%CRAWLER_EXIT%
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$r=Get-Content -Raw -Encoding UTF8 '%REPORT%' | ConvertFrom-Json; [pscustomobject]@{status=$r.status; report='data/daily/latest_report.json'} | ConvertTo-Json -Compress"

rem IMPORTANT FOR N8N:
rem BLOCKED_SOURCE_QUALITY / BLOCKED_INTEGRATION / FAILED are application statuses
rem written to latest_report.json. A fresh report means the command itself completed,
rem so return 0 and let the following n8n nodes branch on report.status.
exit /b 0
