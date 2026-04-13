# Disable facewinunlock-tauri: autostart task + processes + credential provider tiles.
# Backs up affected registry keys so it can be undone.
# Must be run as Administrator.

$ErrorActionPreference = 'Stop'
$backupDir = Join-Path $env:USERPROFILE 'face-unlock-backup'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$cpGuids = @(
    '{8a7b9c6d-4e5f-89a0-8b7c-6d5e4f3e2d1c}',   # FaceWinUnlock-Tauri
    '{8AF662BF-65A0-4D0A-A540-A338A999D36F}'    # unknown FaceCredentialProvider
)

# 1. Backup CP registry keys
foreach ($g in $cpGuids) {
    $key = "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$g"
    $file = Join-Path $backupDir "cp-$($g.Trim('{}'))-$stamp.reg"
    reg export $key $file /y 2>&1 | Out-Null
    Write-Host "Backed up $g -> $file"
}

# 2. Also back up CLSID entries (so we can restore COM registration too)
foreach ($g in $cpGuids) {
    $key = "HKLM\SOFTWARE\Classes\CLSID\$g"
    $file = Join-Path $backupDir "clsid-$($g.Trim('{}'))-$stamp.reg"
    try { reg export $key $file /y 2>&1 | Out-Null } catch {}
}

# 3. Disable scheduled task
try {
    Disable-ScheduledTask -TaskName 'FaceWinUnlockAutoStart' -ErrorAction Stop | Out-Null
    Write-Host "Disabled task FaceWinUnlockAutoStart"
} catch {
    Write-Host "Task not found or already disabled"
}

# 4. Kill running processes
Get-Process | Where-Object { $_.Name -match '^(facewinunlock-tauri|FaceWinUnlock-Server)' } |
    ForEach-Object {
        Write-Host "Killing $($_.Name) (PID $($_.Id))"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }

# 5. Remove CP registrations (tile won't show on lock screen)
foreach ($g in $cpGuids) {
    $path = "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$g"
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
        Write-Host "Removed CP registration: $g"
    }
}

Write-Host ""
Write-Host "Done. Backups saved to: $backupDir" -ForegroundColor Green
Write-Host "To restore later:"
Write-Host "  reg import `"$backupDir\cp-<guid>-<stamp>.reg`""
Write-Host "  Enable-ScheduledTask -TaskName FaceWinUnlockAutoStart"
