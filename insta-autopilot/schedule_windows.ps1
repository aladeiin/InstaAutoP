# Registers a daily Windows Scheduled Task that runs the pipeline.
#
# Usage (PowerShell, from this folder):
#   .\schedule_windows.ps1 -Time "18:30"
#   .\schedule_windows.ps1 -Remove        # delete the task
#
# If the laptop is off or asleep at the scheduled time, the task runs as soon as
# the laptop is next on and online (StartWhenAvailable).

param(
    [string]$Time = "18:30",
    [string]$TaskName = "InstaAutopilot",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    exit 0
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Could not find $Python. Create the virtual environment first (see README step 2)."
}

$Action = New-ScheduledTaskAction -Execute $Python `
    -Argument "main.py run" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Description "Daily Instagram Reel pipeline" -Force | Out-Null

Write-Host "Scheduled '$TaskName' to run daily at $Time."
Write-Host "Logs: $Root\logs\autopilot.log"
Write-Host "Test it now with:  Start-ScheduledTask -TaskName $TaskName"
