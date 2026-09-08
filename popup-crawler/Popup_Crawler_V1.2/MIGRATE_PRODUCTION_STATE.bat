@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] .venv was not found.
  pause
  exit /b 2
)

if not defined POPUP_STATE_DIR set "POPUP_STATE_DIR=%~dp0..\Popup_Crawler_STATE"
if not exist "%POPUP_STATE_DIR%" mkdir "%POPUP_STATE_DIR%" >nul 2>nul
set "POPUP_MASTER_PATH=%POPUP_STATE_DIR%\canonical_master.jsonl"
set "POPUP_PRODUCTION=1"

echo ============================================
echo Popup Crawler production state migration
echo ============================================
echo Master: %POPUP_MASTER_PATH%
echo.

"%PY%" scripts\ensure_production_state.py
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [OK] Production state is ready.
) else (
  echo [ERROR] Production state is not ready. See message above.
  echo If this is truly the first-ever production bootstrap, run once with:
  echo   set POPUP_ALLOW_MASTER_BOOTSTRAP=1
  echo   MIGRATE_PRODUCTION_STATE.bat
)
pause
exit /b %RC%
