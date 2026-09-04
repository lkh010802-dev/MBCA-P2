@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo Popup Crawler v1.0.0 Schedule Status

echo ========================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t = Get-ScheduledTask -TaskName 'PopupCrawlerDaily' -ErrorAction SilentlyContinue; if (-not $t) { Write-Host '[NOT REGISTERED] PopupCrawlerDaily'; exit 2 }; $i = Get-ScheduledTaskInfo -TaskName 'PopupCrawlerDaily'; Write-Host ('State       : ' + $t.State); Write-Host ('Last run    : ' + $i.LastRunTime); Write-Host ('Last result : ' + $i.LastTaskResult); Write-Host ('Next run    : ' + $i.NextRunTime); Write-Host ('Latest log  : ' + (Join-Path (Get-Location) 'logs\scheduler\latest.log'))"
set "EXITCODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXITCODE%
