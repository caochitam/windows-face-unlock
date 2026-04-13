# Face Unlock for Windows

An open-source, auditable replacement for closed-source webcam-login utilities
(like `facewinunlock-tauri`). Three cooperating components:

| Component             | Language | Runs as                 | Role                                                                 |
|-----------------------|----------|-------------------------|----------------------------------------------------------------------|
| `face_service`        | Python   | User session (always)   | Camera + DeepFace + liveness + DPAPI; exposes a named pipe.          |
| `presence_monitor`    | Python   | User session (tray)     | Every 60 s, probe presence; if absent → `LockWorkStation()`.         |
| `credential_provider` | C++      | LogonUI (SYSTEM)        | Windows Credential Provider tile that calls the service on unlock.   |

Plus two CLI tools: `tools.enroll` (capture reference photos) and
`tools.set_password` (store your Windows password encrypted with DPAPI).

## Why three pieces?

Windows lock-screen authentication runs in an isolated session as `SYSTEM`,
which cannot comfortably load TensorFlow / open the webcam. The C++
Credential Provider is therefore a thin shim that communicates with the
heavyweight Python service over a local named pipe. This is the same pattern
Howdy uses on Linux with PAM.

## Features

- **ArcFace (DeepFace) face recognition** with cosine-distance thresholding
- **Anti-spoofing (liveness)** via DeepFace's built-in `anti_spoofing=True`
  (MiniFASNet) — blocks flat photos of your face
- **DPAPI-protected** Windows password storage (user scope)
- **Multi-frame voting** for unlock: N out of M frames must match
- **Presence auto-lock** every minute, with *remote-context exclusion*:
  skips when the session is RDP or when TeamViewer / AnyDesk / RustDesk /
  Parsec / Chrome Remote Desktop / Quick Assist / UltraViewer are actively
  connected. Also skips when input was received recently or when paused
  from the tray icon.
- **System tray control** (pystray) — pause/resume/quit.

## Requirements

- Windows 10 / 11 x64
- Python 3.11 or 3.12
- Webcam
- (For Credential Provider) Visual Studio 2022 + CMake

## Install (Python parts)

```powershell
# From this folder, in PowerShell
.\setup.ps1
```

This creates `.\.venv`, installs dependencies, writes a default config to
`%USERPROFILE%\.face-unlock\config.toml`, and registers Task Scheduler jobs
that run `face_service` and `presence_monitor` at logon.

## Enroll your face + store password

```powershell
.\.venv\Scripts\python -m tools.enroll capture --count 15
.\.venv\Scripts\python -m tools.set_password
```

Rebuild embeddings any time with:

```powershell
.\.venv\Scripts\python -m tools.enroll build
```

## (Optional) Enable the lock-screen tile

See [credential_provider/README.md](credential_provider/README.md). You will
need Visual Studio 2022. Without this, the presence-lock still works — you
just unlock with your password like usual.

## Quick test (no Credential Provider needed)

```powershell
# Terminal 1
.\.venv\Scripts\python -m face_service

# Terminal 2
.\.venv\Scripts\python -m presence_monitor
```

Trigger a manual unlock probe:

```powershell
# Named-pipe one-shot client from PowerShell
$p = New-Object IO.Pipes.NamedPipeClientStream('.', 'FaceUnlock', 'InOut')
$p.Connect(5000)
$w = New-Object IO.StreamWriter($p); $w.AutoFlush = $true
$r = New-Object IO.StreamReader($p)
$w.Write('{"cmd":"verify"}'); $p.WaitForPipeDrain()
$r.ReadToEnd()
```

## Configuration reference

See [config.example.toml](config.example.toml). Key knobs:

- `threshold` — cosine distance cutoff. Lower = stricter. Tune after enrolling.
- `verify_frames` / `verify_required` — multi-frame voting.
- `presence_interval_s` — how often to probe (default 60).
- `presence_absent_strikes` — lock after N consecutive absent ticks (default 2,
  so effective lock timeout is `interval * strikes` = 2 minutes).

## Security notes

Read these before trusting the CP for daily unlock:

1. The stored Windows password is encrypted with **DPAPI user-scope**. That
   protects it from other users and from offline disk inspection, but **not**
   from malware running as you. If your attacker model includes that, use a
   smart card or Windows Hello proper.
2. The pipe currently uses a NULL DACL (any local user can connect). This is
   acceptable for a personal machine but consider tightening to `SELF` +
   `SYSTEM` in `_build_sa_everyone()` if multiple accounts share the PC.
3. Anti-spoofing blocks 2-D photos but **not 3-D masks or deepfake screens**.
4. The credential provider skeleton uses a hard-coded GUID from this repo —
   **generate your own** before sharing builds.

## Credits / prior art

This project draws on ideas from:

- [boltgolt/howdy](https://github.com/boltgolt/howdy) — Linux/PAM face login
- [serengil/deepface](https://github.com/serengil/deepface) — recognition + liveness
- [ageitgey/face_recognition](https://github.com/ageitgey/face_recognition) — dlib wrapper
- Microsoft's [SampleCredentialProvider](https://github.com/microsoft/Windows-classic-samples/tree/main/Samples/CredentialProvider)
  — reference implementation for `ICredentialProvider`

## License

MIT — see [LICENSE](LICENSE) (add one before publishing).
