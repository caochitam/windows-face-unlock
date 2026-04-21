"""End-to-end installer build.

Runs these steps in order (skipping anything already done):
  1. download model weights (DeepFace ArcFace, MiniFASNet v2 + v1SE)
  2. build the Credential Provider DLL via CMake (Release x64)
  3. run PyInstaller on installer/windows_face_unlock.spec
  4. stage the CP DLL + README + license into the PyInstaller dist folder
  5. compile installer/installer.iss with Inno Setup
  6. emit SHA-256 checksums next to the installer

Intended to run both locally and in CI. Environment:
    INNO_SETUP_ISCC — full path to ISCC.exe (default: search PATH)
    SKIP_CP        — set to 1 to skip the C++ DLL (weak default when
                     Visual Studio + CMake aren't available)
"""
from __future__ import annotations
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = REPO_ROOT / "installer"
CP_DIR = REPO_ROOT / "credential_provider"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"
OUTPUT_DIR = REPO_ROOT / "installer_output"


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    log("$ " + " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None, env=env)


def python_exe() -> str:
    return sys.executable


def step_download_weights() -> None:
    log("step 1/6 — download model weights")
    run([python_exe(), str(INSTALLER_DIR / "download_weights.py")], cwd=REPO_ROOT)


def step_build_cp() -> Path | None:
    if os.environ.get("SKIP_CP") == "1":
        log("step 2/6 — skipping Credential Provider DLL (SKIP_CP=1)")
        return None
    log("step 2/6 — build Credential Provider DLL")
    build_path = CP_DIR / "build"
    if build_path.exists():
        shutil.rmtree(build_path, ignore_errors=True)
    try:
        run(["cmake", "-B", "build", "-A", "x64", "-G", "Visual Studio 17 2022"],
            cwd=CP_DIR)
        run(["cmake", "--build", "build", "--config", "Release"], cwd=CP_DIR)
    except subprocess.CalledProcessError as e:
        log(f"CP build failed ({e}); continuing without it. "
            "Installer will mark CP component as missing.")
        return None
    dll = build_path / "Release" / "FaceCredentialProvider.dll"
    if not dll.exists():
        log(f"CP DLL not found at {dll}; skipping")
        return None
    return dll


def step_pyinstaller() -> Path:
    log("step 3/6 — PyInstaller")
    for d in (DIST_DIR, BUILD_DIR):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    run([
        python_exe(), "-m", "PyInstaller",
        "--noconfirm", "--clean",
        str(INSTALLER_DIR / "windows_face_unlock.spec"),
    ], cwd=REPO_ROOT)
    out = DIST_DIR / "WindowsFaceUnlock"
    if not out.exists():
        raise RuntimeError(f"expected PyInstaller output at {out}")
    return out


def step_stage(dist_root: Path, cp_dll: Path | None) -> None:
    log("step 4/6 — stage CP DLL + docs into dist")
    if cp_dll and cp_dll.exists():
        dest = dist_root / "credential_provider"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cp_dll, dest / "FaceCredentialProvider.dll")
        # keep the register script alongside the DLL for the installer
        reg = CP_DIR / "register.ps1"
        if reg.exists():
            shutil.copy2(reg, dest / "register.ps1")
    for doc in ("README.md", "LICENSE", "INSTALL.md"):
        p = REPO_ROOT / doc
        if p.exists():
            shutil.copy2(p, dist_root / doc)


def _find_iscc() -> str:
    env = os.environ.get("INNO_SETUP_ISCC")
    if env and Path(env).exists():
        return env
    for candidate in (
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ):
        if Path(candidate).exists():
            return candidate
    exe = shutil.which("iscc") or shutil.which("ISCC")
    if exe:
        return exe
    raise FileNotFoundError(
        "ISCC.exe (Inno Setup) not found. Install from https://jrsoftware.org/isdl.php "
        "or set INNO_SETUP_ISCC to its path."
    )


def step_inno() -> Path:
    log("step 5/6 — Inno Setup")
    iscc = _find_iscc()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run([iscc, str(INSTALLER_DIR / "installer.iss")], cwd=REPO_ROOT)
    # Expected output: installer_output\WindowsFaceUnlock-Setup-<ver>.exe
    outputs = sorted(OUTPUT_DIR.glob("WindowsFaceUnlock-Setup-*.exe"))
    if not outputs:
        raise RuntimeError(f"Inno Setup produced no artefact in {OUTPUT_DIR}")
    return outputs[-1]


def step_checksums(installer_path: Path) -> None:
    log("step 6/6 — SHA-256 checksums")
    h = hashlib.sha256()
    with installer_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    (installer_path.parent / f"{installer_path.name}.sha256").write_text(
        f"{digest}  {installer_path.name}\n", encoding="ascii"
    )
    log(f"sha256 = {digest}")


def main() -> int:
    step_download_weights()
    cp_dll = step_build_cp()
    dist_root = step_pyinstaller()
    step_stage(dist_root, cp_dll)
    installer_path = step_inno()
    step_checksums(installer_path)
    log(f"Installer ready: {installer_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
