@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not defined POPUP_STATE_DIR set "POPUP_STATE_DIR=%~dp0..\Popup_Crawler_STATE"
set "MASTER=%POPUP_STATE_DIR%\canonical_master.jsonl"
echo Master path: %MASTER%
if not exist "%MASTER%" (
  echo [MISSING] No persistent master.
  pause
  exit /b 1
)
for /f %%C in ('find /v /c "" ^< "%MASTER%"') do set "COUNT=%%C"
echo [OK] master rows: %COUNT%
echo State folder: %POPUP_STATE_DIR%
pause
exit /b 0
