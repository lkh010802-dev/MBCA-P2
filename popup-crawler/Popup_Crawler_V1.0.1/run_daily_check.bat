@echo off
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [SETUP REQUIRED] Run setup.bat once first.
  echo.
  pause
  exit /b 2
)

"%PY%" run_daily.py --reuse-latest --no-commit
set "EXITCODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXITCODE%
