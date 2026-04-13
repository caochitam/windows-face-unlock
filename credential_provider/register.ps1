# Register or unregister the Face Unlock Credential Provider.
# Must be run as Administrator.
param(
    [ValidateSet('register','unregister')]
    [string]$Action = 'register',
    [string]$DllPath = "$PSScriptRoot\build\Release\FaceCredentialProvider.dll"
)

if (-not (Test-Path $DllPath)) {
    Write-Error "DLL not found at $DllPath. Build the project first (see README)."
    exit 1
}

if ($Action -eq 'register') {
    regsvr32 /s $DllPath
    Write-Host "Registered $DllPath"
} else {
    regsvr32 /u /s $DllPath
    Write-Host "Unregistered $DllPath"
}
