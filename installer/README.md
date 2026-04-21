# Installer build

This folder builds the end-user installer that drops Windows Face Unlock
onto a machine that has nothing installed — no Python, no TensorFlow, no
torch, no Visual C++ runtime redist beyond what Windows ships. One `.exe`,
users double-click, done.

Two ways to build: locally (for testing) and in CI (for releases).

## What you get

`installer_output\WindowsFaceUnlock-Setup-<version>.exe` (~350–500 MB
because it bundles Python 3.12, TensorFlow CPU, PyTorch CPU, DeepFace,
OpenCV, pywin32, all models, and the Credential Provider DLL).

Plus `.sha256` next to it.

The installer:
- Copies everything into `C:\Program Files\WindowsFaceUnlock\`.
- Registers scheduled tasks `\FaceUnlock-Service` and `\FaceUnlock-Presence`
  pointing to the bundled exes.
- Optionally registers `FaceCredentialProvider.dll` with `regsvr32` so the
  face tile appears on the Windows lock screen.
- On uninstall: stops tasks, unregisters the DLL, removes all files, and
  asks whether to also wipe `%USERPROFILE%\.face-unlock`.

## Local build

Prerequisites:
- Windows 10 / 11 x64
- Python 3.11 or 3.12 in PATH
- [Inno Setup 6](https://jrsoftware.org/isdl.php) (installs `ISCC.exe`)
- *(Optional)* Visual Studio 2022 Build Tools with the C++ workload — only
  needed to build the Credential Provider DLL. Set `SKIP_CP=1` to skip it
  and release a presence-auto-lock-only build.

Steps from the repo root:

```powershell
# Install dependencies and PyInstaller
.\setup.ps1
.\.venv\Scripts\pip install pyinstaller
.\.venv\Scripts\pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision

# Run the whole pipeline
.\.venv\Scripts\python installer\build.py
```

`build.py` runs, in order:

1. `installer/download_weights.py` — fetch ArcFace + MiniFASNet weights
   into `models/weights/` (skipped if already present).
2. CMake → `credential_provider\build\Release\FaceCredentialProvider.dll`
   (skipped if `SKIP_CP=1`).
3. PyInstaller against `installer/windows_face_unlock.spec` → two exes
   (`face_service.exe`, `face_unlock_tray.exe`) sharing one runtime folder
   in `dist\WindowsFaceUnlock\`.
4. Stage CP DLL + docs into the dist folder.
5. `ISCC.exe installer\installer.iss` → final installer in
   `installer_output\`.
6. SHA-256 checksum next to the installer.

Expect ~15 minutes on a warm venv, mostly PyInstaller analysing
TensorFlow.

### Environment knobs

| Variable           | Effect |
|--------------------|--------|
| `SKIP_CP=1`        | Skip the C++ Credential Provider DLL. Installer still offers the task box but `FileExists` will return false. |
| `INNO_SETUP_ISCC`  | Full path to `ISCC.exe` if it's not at the default `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`. |

## CI build

`.github/workflows/release.yml` reproduces the local pipeline on
`windows-2022` runners and publishes a GitHub Release attached to the
`v<version>` tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The workflow stamps `__version__` and Inno Setup's `MyAppVersion` from the
tag before building.

## Code signing

The installer is published unsigned by default. First-time users will see
Windows SmartScreen flag it as *Unknown publisher* — they click **More info
→ Run anyway**. Acceptable for tinkerers, not ideal for wider distribution.

The workflow integrates with [SignPath.io](https://signpath.io/open-source),
which offers free code signing to vetted open-source projects. Once
approved, add these repository secrets:

| Secret                   | From SignPath |
|--------------------------|---------------|
| `SIGNPATH_API_TOKEN`     | CI token |
| `SIGNPATH_ORG_ID`        | Organization ID |
| `SIGNPATH_PROJECT_SLUG`  | Project slug |

With all three present, the workflow auto-detects them and submits the
installer for signing between PyInstaller and Release publish. Without
them, the unsigned installer goes out unchanged — no workflow edits
needed.

Alternatives if SignPath isn't an option:
- **Certum Open Source Code Signing** — ~USD 25/year, requires ID verification.
- **Azure Trusted Signing** — ~USD 10/month, fastest if you already have
  Azure. Plug into the workflow via `azure/trusted-signing-action`.
- **Self-signed certs do NOT help SmartScreen** — reputation requires a
  CA Microsoft trusts. Don't bother.

## Anatomy

- `windows_face_unlock.spec` — PyInstaller: two Analyses merged via
  `MERGE()` so TF/torch land once. Hidden imports + collected data files
  for TF, tf_keras, deepface, torch, torchvision, cv2. Excludes
  `matplotlib`, `PyQt*`, Jupyter to trim fat.
- `download_weights.py` — grabs the three weights DeepFace needs (ArcFace,
  MiniFASNet v2, MiniFASNet v1SE) into `models/weights/` so the installer
  can bundle them.
- `installer.iss` — Inno Setup script. Admin install, `lzma2/ultra64`,
  `CloseApplications=yes` so the updater can replace files in-place, two
  tasks (CP register + tray autostart), uninstall asks about user data.
- `postinstall/register_tasks.ps1` — called from [Run] to create the two
  scheduled tasks pointing at the installed exes.
- `build.py` — glue script that runs all of the above.

## Updating

The tray process checks GitHub Releases 30 seconds after start and once
every time the user picks *"Check for updates…"* in the tray menu. If a
newer `tag_name` is found with an `.exe` asset, it offers to download +
launch the installer silently (`/SILENT /CLOSEAPPLICATIONS
/RESTARTAPPLICATIONS`). The installer then stops the running tray +
service, replaces files, and restarts both.

See [`presence_monitor/updater.py`](../presence_monitor/updater.py) and
the `[Setup] CloseApplications=yes` line in `installer.iss`.
