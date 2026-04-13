Stop-ScheduledTask -TaskName 'FaceUnlock-Service' -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName 'FaceUnlock-Presence' -ErrorAction SilentlyContinue

Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*face_service*' -or $_.CommandLine -like '*presence_monitor*' } |
    ForEach-Object {
        Write-Host "Killing PID $($_.ProcessId): $($_.CommandLine)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Start-Sleep 2
Start-ScheduledTask -TaskName 'FaceUnlock-Service'
Start-Sleep 1
Start-ScheduledTask -TaskName 'FaceUnlock-Presence'
Write-Host "Started."
