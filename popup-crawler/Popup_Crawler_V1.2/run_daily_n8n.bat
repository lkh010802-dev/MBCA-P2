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

rem ============================================================
rem Production state must live OUTSIDE the replaceable code folder.
rem This prevents a server deploy from resetting persistent popup_id/master.
rem Override POPUP_STATE_DIR before launch if you want another location.
rem ============================================================
if not defined POPUP_STATE_DIR set "POPUP_STATE_DIR=%~dp0..\Popup_Crawler_STATE"
if not exist "%POPUP_STATE_DIR%" mkdir "%POPUP_STATE_DIR%" >nul 2>nul
set "POPUP_MASTER_PATH=%POPUP_STATE_DIR%\canonical_master.jsonl"
set "POPUP_PRODUCTION=1"
set "DAYFORYOU_DETAIL_CACHE_DIR=%POPUP_STATE_DIR%\dayforyou_detail_html"
set "DAYFORYOU_DETAIL_CACHE_HOURS=54"

echo [STATE] POPUP_MASTER_PATH=%POPUP_MASTER_PATH%

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
rem A fresh report means command transport succeeded. Application status is
rem handled by the next n8n nodes from latest_report.json.
exit /b 0
