# Face Unlock — Fresh Install Guide

This captures every lesson learned during the original setup so the next
install on a fresh machine is painless. Read top-to-bottom.

## 0. Prerequisites

| Requirement | Tested version | Install command |
|---|---|---|
| Windows 10/11 x64 | 11 Pro 26200 | — |
| Python 3.11 or 3.12 | 3.12.10 | `winget install Python.Python.3.12` |
| Git | any | `winget install Git.Git` |
| CMake | 4.3 | `winget install Kitware.CMake` |
| VS Build Tools 2022 (C++ workload + Win11 SDK) | 17.14 | see §5 |
| GitHub CLI (optional, for push) | 2.89 | `winget install GitHub.cli` |

## 1. Clone + Python setup

```powershell
git clone <this-repo> C:\Users\<you>\Documents\Projects\face-unlock
cd C:\Users\<you>\Documents\Projects\face-unlock
.\setup.ps1               # creates .venv, installs deps, registers Task Scheduler tasks
```

`requirements.txt` pulls: `deepface`, `opencv-python`, `pywin32`, `psutil`,
`pystray`, `Pillow`, `tomli-w`, `tf-keras`, `tomli` (on 3.10 only).

## 2. Install PyTorch CPU (required for anti-spoofing)

DeepFace's MiniFASNet liveness model needs torch. The default PyPI build is
GPU+huge; use the CPU index:

```powershell
.\.venv\Scripts\pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
```

~200 MB. Skip if you set `anti_spoofing = false` in config.

## 3. Pre-download weights (avoids flaky GitHub CDN)

DeepFace auto-downloads weights at first use but the GitHub release mirror
sometimes rate-limits or fails. Pre-fetch to `%USERPROFILE%\.deepface\weights\`:

```powershell
$w = "$env:USERPROFILE\.deepface\weights"
New-Item -ItemType Directory -Force -Path $w | Out-Null
curl -L -o "$w\arcface_weights.h5" https://github.com/serengil/deepface_models/releases/download/v1.0/arcface_weights.h5
curl -L -o "$w\2.7_80x80_MiniFASNetV2.pth" https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/raw/master/resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth
curl -L -o "$w\4_0_0_80x80_MiniFASNetV1SE.pth" https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/raw/master/resources/anti_spoof_models/4_0_0_80x80_MiniFASNetV1SE.pth
curl -L -o "$w\face_detection_yunet_2023mar.onnx" https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
```

Expected sizes: arcface 131MB, MiniFASNetV2 1.8MB, MiniFASNetV1SE 1.8MB,
yunet 227KB.

## 4. Enrollment + password

```powershell
.\.venv\Scripts\python -m tools.enroll capture --count 15    # look at camera, move head slightly
.\.venv\Scripts\python -m tools.set_password                 # enter Windows password (DPAPI encrypt)
```

Enrollment accepts images where a face is detectable; with 15 captures
expect ~9 usable. Re-run `enroll capture --count 20` if fewer than 6 make it.

`set_password` stores `{user, password, domain}` in
`%USERPROFILE%\.face-unlock\credentials.bin` encrypted with DPAPI (user
scope). Password never leaves your user profile.

## 5. Install Visual Studio Build Tools (only for the Credential Provider)

Skip this section if you only want presence auto-lock without real lock-screen
unlock.

```powershell
winget install Microsoft.VisualStudio.2022.BuildTools --silent --override `
  "--wait --quiet --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.Windows11SDK.22621 --includeRecommended"
```

About 6–8 GB. Takes 10–20 minutes depending on bandwidth.

## 6. Build + register the Credential Provider DLL

```powershell
cd credential_provider
cmake -B build -A x64 -G "Visual Studio 17 2022"
cmake --build build --config Release
# Then, from an Administrator PowerShell:
.\register.ps1 -Action register
```

Uninstall any time: `.\register.ps1 -Action unregister`.

### Gotchas encountered while building

These are already fixed in the source; listed only for troubleshooting.

1. **`FIELD_STATE_PAIR` undefined** — it's in the Microsoft sample set, not
   the public SDK. `helpers.h` defines it locally.
2. **`CPFG_CREDENTIAL_PROVIDER_LOGO` undefined** — same reason. We use
   `GUID_NULL` instead; the tile uses the default logo.
3. **`__ImageBase` undefined in `GetModuleFileNameW`** — because we call it
   directly from `DllRegisterServer`, not via a helper. Leave the
   `EXTERN_C IMAGE_DOS_HEADER __ImageBase;` at end of `dll.cpp`.
4. **`__try/__except` + C++ objects** — MSVC rejects it; use `try/catch`
   instead (already done).
5. **"Parameter is incorrect" from LogonUI** — two separate bugs:
   - `UNICODE_STRING.Buffer` inside the serialization must be an **offset**
     (in bytes from the start of the buffer), NOT an absolute pointer. LSA
     does the fixup across process boundaries.
   - Authentication package: use `"Negotiate"` (NEGOSSP_NAME_A), not
     `"Kerberos"`. Negotiate auto-picks Kerberos vs NTLM and works for
     local accounts. Do NOT fall through to `pkgId = 0` on lookup failure —
     return `HRESULT_FROM_NT(status)`.
6. **GUID must be unique** — replace `CLSID_FaceCredentialProvider` in
   `guid.h` with a freshly generated one (`uuidgen`) before distributing.

## 7. Runtime behaviour

### Config knobs (`%USERPROFILE%\.face-unlock\config.toml`)

| Key | Default | Notes |
|---|---|---|
| `model_name` | `ArcFace` | DeepFace model |
| `detector_backend` | `yunet` | Faster + more accurate than opencv Haar |
| `threshold` | `0.45` | Cosine distance cutoff; lower = stricter |
| `anti_spoofing` | `true` | Requires torch |
| `camera_warmup_frames` | `10` | Helps dim lock-screen lighting |
| `persistent_camera` | `false` | `true` = ~0.9s verify, LED always on. `false` = ~3s verify, LED only while verifying. |
| `verify_frames` | `5` | Captured per unlock |
| `verify_required` | `2` | Matches needed |
| `presence_interval_s` | `60` | Presence auto-lock tick |
| `presence_absent_strikes` | `2` | Lock after N absent ticks |

### Services

Task Scheduler registers two logon tasks (created by `setup.ps1`):

- **FaceUnlock-Service** — the Python pipe server (`\\.\pipe\FaceUnlock`)
- **FaceUnlock-Presence** — the tray app + 60s camera probe

Restart both after editing config:

```powershell
powershell -ExecutionPolicy Bypass -File tools\clean_restart.ps1
```

### Environment variables that matter

Set in `face_service/__main__.py` to stop TensorFlow from spawning extra
worker processes that compete for the pipe:

```
OMP_NUM_THREADS=1
TF_NUM_INTRAOP_THREADS=1
TF_NUM_INTEROP_THREADS=1
CUDA_VISIBLE_DEVICES=-1
```

### Remote-session exclusion

`presence_monitor/remote_session.py` skips auto-lock when:

- RDP session is active (`GetSystemMetrics(SM_REMOTESESSION)`)
- Known remote-control process holds an ESTABLISHED external TCP connection
  (UltraViewer, AnyDesk, RustDesk, Parsec, Chrome Remote Desktop, Splashtop)
- Process name-only match for tools that only run during active sessions
  (TeamViewer_Desktop.exe, Quick Assist, MSRA)

Tune the list in that file if your remote tool is missing.

### Lock-screen auto-trigger

`FaceCredentialProvider::GetCredentialCount` returns
`pbAutoLogonWithDefault = TRUE` and `FaceCredential::SetSelected` returns
`pbAutoLogon = TRUE`. Result: as soon as the lock screen appears (key
press / mouse motion), the face tile is selected and verification runs
automatically.

Safety: `GetSerialization` has a hard 12-second timeout and returns
`S_FALSE` on failure, so a bad verify cannot lock the user out of the
password tile.

## 8. If you also have `facewinunlock-tauri` installed

Run the disable script once (as Administrator) to turn off its autostart,
kill its processes, and remove its Credential Provider registrations
(backed up first):

```powershell
tools\disable_tauri.ps1
```

Backup lives at `%USERPROFILE%\face-unlock-backup\` — `reg import` those
files to restore if needed.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot open camera index 0` | Close other camera apps; Teams/Zoom/UltraViewer can hold the device. Try `camera_index = 1`. |
| Enrollment says "No face found" on all images | Lighting too dim, or you weren't centred. Re-run `enroll capture --count 20`. |
| Verify is slow (>5s per call) | Models didn't pre-warm. Check `service.log` for "model warmup ok". Restart service. |
| Two `python.exe` processes for one service | Normal — venv launcher spawns the real interpreter. Only the inner one runs our code. |
| `Parameter is incorrect` on lock screen | You're running an old DLL. Re-run `cmake --build build --config Release` and lock/unlock once to reload. |
| Lock screen hangs for ~12 s | FaceService is down. `Start-ScheduledTask FaceUnlock-Service`. |
| User stuck, can't reach password | Click "Sign-in options" link on lock screen → pick Password tile. Or boot into Safe Mode; third-party CPs are disabled there. |

## 10. Logs

- `%USERPROFILE%\.face-unlock\service.log` — FaceService
- `%USERPROFILE%\.face-unlock\presence.log` — PresenceMonitor
- Event Viewer → Applications and Services Logs → Microsoft → Windows →
  User Profile Service / Authentication — for LogonUI / LSA errors when
  debugging Credential Provider issues

## 11. Uninstall completely

```powershell
# Admin PowerShell
.\credential_provider\register.ps1 -Action unregister
Unregister-ScheduledTask -TaskName 'FaceUnlock-Service' -Confirm:$false
Unregister-ScheduledTask -TaskName 'FaceUnlock-Presence' -Confirm:$false
Remove-Item -Recurse -Force "$env:USERPROFILE\.face-unlock"
Remove-Item -Recurse -Force .\.venv
```

The repo can then be deleted.
