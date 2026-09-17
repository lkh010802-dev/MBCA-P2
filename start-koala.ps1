$ErrorActionPreference = 'Stop'

$mvpRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Join-Path $mvpRoot 'backend'
$frontendRoot = Join-Path $mvpRoot 'frontend'

if (-not (Test-Path -LiteralPath (Join-Path $backendRoot 'run.py'))) {
  throw "backend\run.py를 찾을 수 없습니다."
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'package.json'))) {
  throw "frontend\package.json을 찾을 수 없습니다."
}

# 기존 프로젝트 가상환경을 우선 사용하고, 없으면 PATH의 python을 사용합니다.
$pythonExe = 'python'
$legacyPython = 'C:\Users\Admin\p2\backend\MBCA-P2-mvp2-integrated\.audit-venv\Scripts\python.exe'
if (Test-Path -LiteralPath $legacyPython) { $pythonExe = $legacyPython }

function Stop-KoalaListener([int]$port) {
  # Get-NetTCPConnection은 일부 일반 사용자 환경에서 접근 거부가 발생한다.
  # netstat 결과를 사용해 IPv4/IPv6 및 0.0.0.0/127.0.0.1 리스너를 모두 찾는다.
  $processIds = @(
    # Do not use `-p tcp`: on Windows it omits the IPv6 TCP listener that
    # Vite creates for localhost, leaving an old frontend alive on ::1.
    netstat -ano |
      Select-String -Pattern "^\s*TCP\s+\S+:$port\s+\S+\s+LISTENING\s+(\d+)\s*$" |
      ForEach-Object { [int]$_.Matches[0].Groups[1].Value } |
      Sort-Object -Unique
  )
  foreach ($processId in $processIds) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    $command = [string]$process.CommandLine
    $safeFallbackMatch = $false
    if ([string]::IsNullOrWhiteSpace($command)) {
      $processName = (Get-Process -Id $processId -ErrorAction SilentlyContinue).ProcessName
      if ($port -eq 8000 -and $processName -match '^python') {
        try {
          $identity = Invoke-RestMethod -Uri "http://127.0.0.1:$port/" -TimeoutSec 2
          $safeFallbackMatch = $identity.version -eq 'mvp2-integrated-extensions'
        } catch { $safeFallbackMatch = $false }
      } elseif ($port -in 5173, 5174 -and $processName -match '^node') {
        try {
          $page = (Invoke-WebRequest -Uri "http://localhost:$port/" -TimeoutSec 2).Content
          $safeFallbackMatch = $page -match '<div id="root"></div>' -and $page -match '/@vite/client'
        } catch { $safeFallbackMatch = $false }
      }
    }
    if ($command -match 'uvicorn|vite' -or $safeFallbackMatch) {
      Stop-Process -Id $processId -Force -ErrorAction Stop
      Start-Sleep -Milliseconds 300
    } else {
      throw "포트 $port 을 다른 프로그램이 사용 중입니다. PID $processId 을 확인해 주세요."
    }
  }
}

# 예전 프로젝트 서버가 남아 최신 코드를 가리는 일을 막는다.
Stop-KoalaListener 8000
Stop-KoalaListener 5173
Stop-KoalaListener 5174

Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
  '-NoProfile', '-Command',
  "Set-Location -LiteralPath '$backendRoot'; & '$pythonExe' -m uvicorn run:app --host 0.0.0.0 --port 8000"
)

Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
  '-NoProfile', '-Command',
  "Set-Location -LiteralPath '$frontendRoot'; npm run dev -- --host localhost --port 5173 --strictPort --configLoader runner"
)

$deadline = (Get-Date).AddSeconds(30)
$backendVersion = $null
do {
  try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/' -TimeoutSec 2
    $backendVersion = $health.version
  } catch {
    Start-Sleep -Milliseconds 500
  }
} while (-not $backendVersion -and (Get-Date) -lt $deadline)

if ($backendVersion -ne 'mvp2-integrated-extensions') {
  throw "통합 백엔드 확인에 실패했습니다. 확인된 버전: $backendVersion"
}

$frontendReady = $false
$frontendDeadline = (Get-Date).AddSeconds(30)
do {
  try {
    $frontendPage = (Invoke-WebRequest -Uri 'http://localhost:5173/' -TimeoutSec 2).Content
    $frontendReady = $frontendPage -match '<div id="root"></div>' -and $frontendPage -match '/@vite/client'
  } catch {
    Start-Sleep -Milliseconds 500
  }
} while (-not $frontendReady -and (Get-Date) -lt $frontendDeadline)

if (-not $frontendReady) {
  throw '프론트엔드 준비 확인에 실패했습니다. 5173 포트의 Vite 로그를 확인해 주세요.'
}

Write-Host 'KOALA 백엔드와 프론트엔드를 시작했습니다.' -ForegroundColor Green
Write-Host '프론트: http://localhost:5173 또는 Vite가 표시한 주소'
Write-Host '백엔드: http://localhost:8000'
