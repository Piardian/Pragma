$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batchPath = Join-Path $projectDir "run_shadow_trader.bat"
if (-not (Test-Path $batchPath)) {
    throw "run_shadow_trader.bat was not found in $projectDir"
}

$taskName = "Pragma Shadow Trader"
$taskArguments = '/c "' + $batchPath + '"'
$action = New-ScheduledTaskAction -Execute "$env:ComSpec" -Argument $taskArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Starts Pragma's broker-free virtual trading service when this Windows user signs in." -Force | Out-Null

Write-Host "Installed task: $taskName"
Write-Host "It starts after Windows sign-in. The PC must be powered on and the user signed in."
Write-Host "MT5 must be installed and logged in for read-only prices; Pragma never submits broker orders."
Write-Host "To start now, run .\run_shadow_trader.bat"
