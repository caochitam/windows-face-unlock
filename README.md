# Windows Face Unlock — face login + presence auto-lock for Windows 10/11

**An open-source Windows face recognition login and walk-away auto-lock —
the kind of "Howdy for Windows" / Windows Hello alternative that stays on
your machine, runs on any off-the-shelf webcam, and you can actually read
the source of.**

Keywords: *windows face unlock, windows face login, face recognition
windows, webcam login windows, howdy windows, windows hello alternative,
credential provider face, deepface windows, arcface windows, auto lock
when away, presence monitor, walk-away lock, face id for pc.*

| | |
|---|---|
| Platform | Windows 10 / 11 x64 |
| Python   | 3.11 or 3.12 |
| License  | MIT |
| Models   | ArcFace + MiniFASNet (DeepFace) + YuNet (OpenCV Zoo) |

## Features at a glance

- **Log in with your face** from the Windows lock screen via a proper
  Credential Provider tile (C++ DLL), not a user-mode hack.
- **Walk-away auto-lock**: every minute the tray process probes the webcam;
  if your enrolled face isn't there, `LockWorkStation()` fires.
- **Two presence modes**: strict (must match the enrolled face, blocks
  strangers) or lightweight (any face is enough, replaces old AutoFaceLock
  scripts).
- **Anti-spoofing** (liveness, MiniFASNet) blocks flat photos and videos
  of your face.
- **Remote-session aware**: skips auto-lock when the session is RDP, or
  when TeamViewer / AnyDesk / RustDesk / Parsec / Chrome Remote Desktop /
  Quick Assist / UltraViewer hold an active remote connection.
- **Managed from the tray**: live status dashboard, settings editor,
  guided enrollment wizard with live camera preview + auto-capture, one
  Quit button that actually stops everything.
- **12-language UI** — English, Tiếng Việt, 中文, Español, Français,
  Deutsch, 日本語, 한국어, Русский, Português, العربية, हिन्दी. Switch
  from the tray, applies live.
- **DPAPI-encrypted** Windows password storage (user scope).

## Architecture

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
- **Two presence modes** (`presence_mode` in config):
  - `recognition` (default) — enrolled face must match (strong; walk-away +
    stranger detection).
  - `detection` — *any* face in frame is enough, via YuNet (weaker; replaces
    the old standalone AutoFaceLock script).
- **System tray management UI** (pystray + tkinter) — Status dashboard,
  Settings editor, Enroll / Set-password shortcuts, Pause/Resume, and a
  single Quit that stops both service and tray cleanly.

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

## Contributing

Issues and PRs are welcome. Before sending a PR please:

- Run `python -m tools.bench` if you touched the recognizer / camera paths.
- Keep new UI strings translatable — add keys to
  [`face_service/i18n.py`](face_service/i18n.py) under all 12 languages
  (English fallback is automatic if a key is missing).
- Generate your own GUID in `credential_provider/guid.h` if you're going
  to register the CP DLL on your machine.

## License

MIT — see [LICENSE](LICENSE).
