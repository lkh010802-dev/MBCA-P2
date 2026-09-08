@echo off
setlocal
title n8n - Popup Crawler

rem n8n v2: enable Execute Command for this process.
set "NODES_EXCLUDE=[]"

rem Use Korea time for n8n schedules/date-time expressions.
set "GENERIC_TIMEZONE=Asia/Seoul"
set "TZ=Asia/Seoul"

echo ============================================
echo   n8n Popup Crawler launcher v2
echo ============================================
echo.
echo NODES_EXCLUDE=%NODES_EXCLUDE%
echo GENERIC_TIMEZONE=%GENERIC_TIMEZONE%
echo TZ=%TZ%
echo.
echo Starting n8n...
echo.

where n8n >nul 2>&1
if errorlevel 1 (
    echo [ERROR] n8n command was not found.
    pause
    exit /b 1
)

call n8n
set "N8N_EXIT_CODE=%ERRORLEVEL%"
echo.
echo n8n stopped. Exit code: %N8N_EXIT_CODE%
pause
exit /b %N8N_EXIT_CODE%
