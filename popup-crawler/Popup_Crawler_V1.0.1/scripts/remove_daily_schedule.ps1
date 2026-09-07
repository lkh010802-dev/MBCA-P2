param([string]$TaskName = "PopupCrawlerDaily")
$ErrorActionPreference = "Stop"

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principalCheck = New-Object System.Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principalCheck.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -TaskName `"$TaskName`""
    $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argLine -Wait -PassThru
    exit $proc.ExitCode
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "[NOTICE] Scheduled task does not exist: $TaskName"
    exit 0
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[SUCCESS] Scheduled task removed: $TaskName"
