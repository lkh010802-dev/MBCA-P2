@echo off
setlocal

cd /d "%~dp0"

echo ========================================
echo Popup Crawler Launcher Builder
echo ========================================
echo.

set "CSC64=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
set "CSC32=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"

if exist "%CSC64%" (
    set "CSC=%CSC64%"
) else if exist "%CSC32%" (
    set "CSC=%CSC32%"
) else (
    echo [ERROR] C# compiler csc.exe를 찾을 수 없습니다.
    echo.
    pause
    exit /b 1
)

if not exist "launcher\PopupCrawlerLauncher.cs" (
    echo [ERROR] launcher\PopupCrawlerLauncher.cs 없음
    pause
    exit /b 1
)

if not exist "assets\koala_run.ico" (
    echo [ERROR] assets\koala_run.ico 없음
    pause
    exit /b 1
)

echo [1/2] Launcher compiling...

"%CSC%" ^
    /nologo ^
    /target:winexe ^
    /reference:System.Windows.Forms.dll ^
    /win32icon:"assets\koala_run.ico" ^
    /out:"Popup Crawler.exe" ^
    "launcher\PopupCrawlerLauncher.cs"

if errorlevel 1 (
    echo.
    echo [ERROR] Launcher build failed.
    pause
    exit /b 1
)

echo.
echo [2/2] Build completed.
echo.
echo ========================================
echo   Popup Crawler.exe created!
echo ========================================
echo.

if exist "Popup Crawler.exe" (
    echo [OK] Popup Crawler.exe
) else (
    echo [ERROR] exe file not found.
)

echo.
pause