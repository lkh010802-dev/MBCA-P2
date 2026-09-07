param(
    [string]$TaskName = "PopupCrawlerDaily",
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Time = "08:00"
)

$ErrorActionPreference = "Stop"

# Register-ScheduledTask can require elevation depending on local policy.
# Re-launch this script once with UAC when necessary; the task itself still runs Limited.
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principalCheck = New-Object System.Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principalCheck.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -TaskName `"$TaskName`" -Time `"$Time`""
    $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argLine -Wait -PassThru
    exit $proc.ExitCode
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runner = Join-Path $ProjectRoot "run_daily_scheduled.bat"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EnvFile = Join-Path $ProjectRoot ".env"

if (-not (Test-Path -LiteralPath $Runner)) {
    throw "Scheduled runner not found: $Runner"
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw ".venv not found. Run setup.bat first."
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw ".env not found. Run setup.bat and configure OPENAI_API_KEY first."
}

$keyLine = Get-Content -LiteralPath $EnvFile -Encoding UTF8 |
    Where-Object { $_ -match '^\s*OPENAI_API_KEY\s*=' } |
    Select-Object -First 1
if (-not $keyLine -or $keyLine -match 'your-key-here|^\s*OPENAI_API_KEY\s*=\s*$') {
    throw "OPENAI_API_KEY is missing or still a placeholder in .env."
}

$parts = $Time.Split(':')
$at = [datetime]::Today.AddHours([int]$parts[0]).AddMinutes([int]$parts[1])
$action = New-ScheduledTaskAction `
    -Execute $env:ComSpec `
    -Argument ('/d /c ""{0}""' -f $Runner) `
    -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $at
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Popup Crawler v1.0.0 daily crawl/integration/backend CSV export" `
    -Force | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ""
Write-Host "[SUCCESS] Scheduled task registered."
Write-Host "Task name : $TaskName"
Write-Host "Daily time: $Time"
Write-Host "Run as    : $currentUser (only while logged on)"
Write-Host "Runner    : $Runner"
Write-Host "Next run  : $($info.NextRunTime)"
Write-Host "Logs      : $ProjectRoot\logs\scheduler\"
