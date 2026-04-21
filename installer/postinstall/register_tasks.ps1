# Registers Task Scheduler jobs for the installed Windows Face Unlock.
# Called by Inno Setup during [Run]. The dev-mode script
# tools/register_tasks.ps1 is separate because it points to .venv\pythonw.exe
# instead of frozen exes.
param(
    [Parameter(Mandatory=$true)] [string] $Service,
    [Parameter(Mandatory=$true)] [string] $Tray
)

$ErrorActionPreference = 'Stop'

function Register-HiddenTask {
    param([string] $Name, [string] $Execute, [string] $WorkingDirectory)
    $action  = New-ScheduledTaskAction  -Execute $Execute -WorkingDirectory $WorkingDirectory
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $prins   = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                                            -StartWhenAvailable -Hidden
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Principal $prins `
                           -Settings $set -Force | Out-Null
    Write-Host "Registered: $Name -> $Execute"
}

$InstallDir = Split-Path -Parent $Service

# Replace any previous registration cleanly.
Unregister-ScheduledTask -TaskName 'FaceUnlock-Service'  -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'FaceUnlock-Presence' -Confirm:$false -ErrorAction SilentlyContinue

Register-HiddenTask -Name 'FaceUnlock-Service'  -Execute $Service -WorkingDirectory $InstallDir
Register-HiddenTask -Name 'FaceUnlock-Presence' -Execute $Tray    -WorkingDirectory $InstallDir

Write-Host "Scheduled tasks registered."
