# Bootstrap script for Face Unlock.
# Creates a venv, installs Python deps, sets up autostart for FaceService
# and PresenceMonitor via Task Scheduler (logon trigger, per-user).

param(
    [string]$PythonExe = "python",
    [switch]$SkipAutostart
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

Write-Host "== Face Unlock setup ==" -ForegroundColor Cyan

# 1. venv
if (-not (Test-Path "$root\.venv")) {
    & $PythonExe -m venv "$root\.venv"
}
$py = "$root\.venv\Scripts\python.exe"

& $py -m pip install --upgrade pip
& $py -m pip install -r "$root\requirements.txt"

# 2. config
$home_cfg = Join-Path $env:USERPROFILE ".face-unlock"
if (-not (Test-Path $home_cfg)) { New-Item -ItemType Directory -Path $home_cfg | Out-Null }
if (-not (Test-Path "$home_cfg\config.toml")) {
    Copy-Item "$root\config.example.toml" "$home_cfg\config.toml"
    Write-Host "Wrote default config to $home_cfg\config.toml"
}

if ($SkipAutostart) { Write-Host "Skipping autostart registration."; return }

# 3. Task Scheduler entries
$pyw = "$root\.venv\Scripts\pythonw.exe"  # windowed (no console) variant
function Register-LogonTask {
    param([string]$Name, [string]$Script)
    $action  = New-ScheduledTaskAction -Execute $pyw -Argument "-m $Script" -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $prins   = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -Hidden
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Principal $prins -Settings $set -Force | Out-Null
    Write-Host "Registered task (hidden, pythonw): $Name"
}

Register-LogonTask -Name "FaceUnlock-Service"  -Script "face_service"
Register-LogonTask -Name "FaceUnlock-Presence" -Script "presence_monitor"

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. $py -m tools.enroll capture --count 15"
Write-Host "  2. $py -m tools.set_password"
Write-Host "  3. (Optional) Build + register the C++ Credential Provider - see credential_provider\README.md"
