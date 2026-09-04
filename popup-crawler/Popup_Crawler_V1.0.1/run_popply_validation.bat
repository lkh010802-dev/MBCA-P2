@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv Python을 찾지 못했습니다.
  echo 먼저 README의 최초 설치 단계를 실행하세요.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" run_popply.py --details --detail-limit 5
set "POPPY_EXIT=%ERRORLEVEL%"

if not "%POPPY_EXIT%"=="0" echo [ERROR] Popply 검증 실행이 실패했습니다.
pause
exit /b %POPPY_EXIT%
