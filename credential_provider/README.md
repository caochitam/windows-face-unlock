# Face Unlock Credential Provider (C++)

A minimal Windows Credential Provider that — when the user selects its tile on
the logon / lock screen — connects to the Python `FaceService` over a named
pipe (`\\.\pipe\FaceUnlock`), asks it to perform face verification, receives
the stored Windows credentials (decrypted via DPAPI in the user context), and
hands them to LogonUI through a standard
`KERB_INTERACTIVE_UNLOCK_LOGON` serialization.

## Build (Visual Studio 2022)

Prerequisites:
- Visual Studio 2022 with **Desktop development with C++** workload
- CMake 3.20+
- Windows SDK 10 (any recent version)

```powershell
cd credential_provider
cmake -B build -A x64
cmake --build build --config Release
```

Output: `build\Release\FaceCredentialProvider.dll`.

## Register (Administrator PowerShell)

```powershell
.\register.ps1 -Action register
```

To remove: `.\register.ps1 -Action unregister`.

Registration writes:
- `HKCR\CLSID\{F8A0B4D9-...}` — COM class
- `HKCR\CLSID\{F8A0B4D9-...}\InprocServer32` — DLL path, Apartment threading
- `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{F8A0B4D9-...}`
  — enables the CP in LogonUI

After (un)registering, lock the workstation (Win+L) and the new "Face Unlock"
tile should appear.

## How it talks to the Python service

1. User selects the Face Unlock tile on lock screen.
2. `SetSelected` returns `*pbAutoLogon = TRUE`, so LogonUI immediately calls
   `GetSerialization`.
3. `GetSerialization` opens `\\.\pipe\FaceUnlock`, sends
   `{"cmd":"unlock"}`, and waits up to 45 s.
4. `FaceService` performs the camera capture + DeepFace verify + liveness
   check, decrypts the DPAPI password blob, and returns
   `{"ok":true,"username":"...","password":"...","domain":"..."}`.
5. The CP packs those into a `KERB_INTERACTIVE_UNLOCK_LOGON` and returns
   `CPGSR_RETURN_CREDENTIAL_FINISHED`. LogonUI performs the actual logon.

## Important caveats

- **The DLL runs inside `LogonUI.exe` under the `SYSTEM` account.** Because
  the DPAPI blob is encrypted with the *user* key, the Python service (which
  runs in the user session) is the one that decrypts it and passes plaintext
  over the pipe — the CP itself never touches DPAPI. The pipe is local-only
  and uses a NULL DACL, which is fine but you should understand the threat
  model before deploying widely.
- This is a **skeleton**: no custom tile bitmap, no localisation, no progress
  UI while the service captures frames, and only the single "unlock /
  interactive logon" scenario is implemented. The Microsoft
  [SampleCredentialProvider](https://github.com/microsoft/Windows-classic-samples/tree/main/Samples/CredentialProvider)
  is a good reference for polishing.
- The `CLSID_FaceCredentialProvider` GUID in `guid.h` is shared with the
  world. **Generate your own** (`uuidgen.exe`) before publishing or
  distributing builds.
- If `GetSerialization` returns `S_FALSE` the user can fall back to the
  standard password tile.
