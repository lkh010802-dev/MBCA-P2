param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$backendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $backendDir

if (-not $PythonPath) {
    $candidates = @(
        (Join-Path $backendDir ".audit-venv\Scripts\python.exe"),
        (Join-Path $projectDir ".audit-venv\Scripts\python.exe"),
        "C:\Users\Admin\p2\backend\MBCA-P2-mvp2-integrated\.audit-venv\Scripts\python.exe"
    )
    $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not $PythonPath) {
    throw "테스트용 Python을 찾지 못했습니다. -PythonPath로 python.exe 경로를 지정해 주세요."
}

function Invoke-TestGroup {
    param(
        [string]$Name,
        [string]$WorkingDirectory
    )

    Write-Host "`n[$Name]" -ForegroundColor Cyan
    Push-Location $WorkingDirectory
    try {
        & $PythonPath -m pytest -q -p no:cacheprovider
        if ($LASTEXITCODE -ne 0) {
            throw "$Name 테스트가 실패했습니다."
        }
    }
    finally {
        Pop-Location
    }
}

# 동일한 이름의 core/extension 모듈이 sys.modules에서 충돌하지 않도록
# 각 pytest 호출을 별도 Python 프로세스로 실행한다.
Invoke-TestGroup -Name "upstream core" -WorkingDirectory (Join-Path $backendDir "core")
Invoke-TestGroup -Name "integrated extensions" -WorkingDirectory $backendDir

Write-Host "`nKOALA 백엔드 전체 검증 통과" -ForegroundColor Green

