param(
    [string]$TaskName = 'CodexAirportVideoIndex'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.conda\experiment\python.exe'
$indexer = Join-Path $projectRoot 'runs\failure_videos\update_scene_video_index.py'
foreach ($path in @($python, $indexer)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required file is missing: $path"
    }
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument ('"' + $indexer + '" --refresh-server') `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force `
    -Description 'Refresh the airport simulation server video index every 5 minutes.' | Out-Null
Start-ScheduledTask -TaskName $TaskName
Get-ScheduledTaskInfo -TaskName $TaskName |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
