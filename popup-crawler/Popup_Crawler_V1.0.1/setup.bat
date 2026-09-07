@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo Popup Crawler v1.0.1 One-time Setup

echo ========================================
echo.

if exist ".venv\Scripts\python.exe" goto INSTALL

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 goto FAIL

:INSTALL
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto FAIL
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto FAIL
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto FAIL

if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo.
  echo [NOTICE] .env was created from .env.example.
  echo          Put OPENAI_API_KEY in .env before Daily/LLM execution.
echo          Put KAKAO_REST_API_KEY in .env to auto-fill missing coordinates.
)

if not exist "output" mkdir "output"
if not exist "logs\scheduler" mkdir "logs\scheduler"

echo.
echo [SUCCESS] Setup completed.
echo 1. Edit .env and set OPENAI_API_KEY.
echo 2. Set KAKAO_REST_API_KEY for missing latitude/longitude enrichment.
echo 3. Run run_daily.bat once manually.
echo 4. Run setup_daily_schedule.bat to register daily 08:00 execution.
echo.
pause
exit /b 0

:FAIL
echo.
echo [FAILED] Setup failed. Check the error above.
echo.
pause
exit /b 1
