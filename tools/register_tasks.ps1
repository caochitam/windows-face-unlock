# Re-register the FaceUnlock tasks to run with pythonw.exe (no CMD window)
# and the hidden-task attribute set. Safe to re-run.
$root = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $root '.venv\Scripts\pythonw.exe'

function Register-HiddenTask {
    param([string]$Name, [string]$Module)
    $action  = New-ScheduledTaskAction -Execute $py -Argument "-m $Module" -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $prins   = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -Hidden
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Principal $prins -Settings $set -Force | Out-Null
    Write-Host "Registered (hidden, pythonw): $Name"
}

Register-HiddenTask -Name 'FaceUnlock-Service'  -Module 'face_service'
Register-HiddenTask -Name 'FaceUnlock-Presence' -Module 'presence_monitor'

# Stop anything running then restart with new settings
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*face_service*' -or $_.CommandLine -like '*presence_monitor*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Sleep 1
Start-ScheduledTask -TaskName 'FaceUnlock-Service'
Start-ScheduledTask -TaskName 'FaceUnlock-Presence'
Write-Host "Started."
