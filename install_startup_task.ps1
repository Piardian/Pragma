$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batchPath = Join-Path $projectDir "run_scanner.bat"
if (-not (Test-Path $batchPath)) {
    throw "run_scanner.bat was not found in $projectDir"
}

$taskName = "Pragma Market Scanner"
$taskArguments = '/c "' + $batchPath + '"'
$action = New-ScheduledTaskAction -Execute "$env:ComSpec" -Argument $taskArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Starts the Pragma 15-minute market scanner when this Windows user logs in." -Force | Out-Null

Write-Host "Installed task: $taskName"
Write-Host "It starts when you sign in to Windows, not before login."
Write-Host "MetaTrader 5 must be running and logged in for market data."
Write-Host "To start now, run .\run_scanner.bat"
