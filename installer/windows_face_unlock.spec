# PyInstaller spec — builds face_service.exe and face_unlock_tray.exe into a
# single shared dist folder. Run from the repo root:
#     pyinstaller installer/windows_face_unlock.spec --noconfirm --clean
#
# The two entry points share runtime binaries via MERGE so TensorFlow and
# torch are only laid down once (~250 MB saved).

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.building.api import PYZ, EXE, COLLECT, MERGE
from PyInstaller.building.build_main import Analysis

REPO_ROOT = Path(SPECPATH).resolve().parent
BLOCK_CIPHER = None

# ---------------------------------------------------------------------------
# Hidden imports + data collection — TF / DeepFace / torch are hostile to
# static analysis, so we help PyInstaller find everything.
# ---------------------------------------------------------------------------
HIDDEN = []
HIDDEN += collect_submodules("tensorflow")
HIDDEN += collect_submodules("tf_keras")
HIDDEN += collect_submodules("keras")
HIDDEN += collect_submodules("deepface")
HIDDEN += collect_submodules("torch")
HIDDEN += collect_submodules("torchvision")
HIDDEN += [
    "pystray._win32",
    "PIL._tkinter_finder",
    "win32api", "win32security", "win32file", "win32pipe",
    "win32event", "win32process", "winerror",
    "pywintypes",
    "presence_monitor.enroll_gui",
    "presence_monitor.gui",
    "presence_monitor.updater",
    "presence_monitor.widgets",
    "face_service.i18n",
    "face_service.detector",
    "face_service._version",
]

DATAS = []
DATAS += collect_data_files("tensorflow")
DATAS += collect_data_files("tf_keras")
DATAS += collect_data_files("keras")
DATAS += collect_data_files("deepface")
DATAS += collect_data_files("torch")
DATAS += collect_data_files("cv2")

# Bundle YuNet model + DeepFace weights.
DATAS += [
    (str(REPO_ROOT / "models" / "face_detection_yunet_2023mar.onnx"), "models"),
]
weights_dir = REPO_ROOT / "models" / "weights"
if weights_dir.exists():
    for p in weights_dir.iterdir():
        if p.is_file():
            DATAS.append((str(p), "models/weights"))

EXCLUDES = [
    # Reduce size: drop things DeepFace pulls in but we never exercise.
    "matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "jupyter", "ipykernel", "notebook",
    "tensorflow.lite.experimental.microfrontend",
    "scipy.spatial.cKDTree",  # huge, unused
]

# ---------------------------------------------------------------------------
# Two entry points.
# ---------------------------------------------------------------------------
service_analysis = Analysis(
    [str(REPO_ROOT / "face_service" / "__main__.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    cipher=BLOCK_CIPHER,
    noarchive=False,
)

tray_analysis = Analysis(
    [str(REPO_ROOT / "presence_monitor" / "__main__.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN + ["tkinter", "tkinter.ttk", "tkinter.messagebox"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    cipher=BLOCK_CIPHER,
    noarchive=False,
)

# Share Python DLLs + site-packages between the two EXEs to avoid doubling
# the bundle size.
MERGE(
    (service_analysis, "face_service", "face_service"),
    (tray_analysis, "face_unlock_tray", "face_unlock_tray"),
)

service_pyz = PYZ(service_analysis.pure, service_analysis.zipped_data, cipher=BLOCK_CIPHER)
tray_pyz = PYZ(tray_analysis.pure, tray_analysis.zipped_data, cipher=BLOCK_CIPHER)

service_exe = EXE(
    service_pyz,
    service_analysis.scripts,
    [],
    exclude_binaries=True,
    name="face_service",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # service has no UI; log to file
    windowed=True,
    disable_windowed_traceback=False,
    icon=None,
)

tray_exe = EXE(
    tray_pyz,
    tray_analysis.scripts,
    [],
    exclude_binaries=True,
    name="face_unlock_tray",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    windowed=True,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    service_exe,
    service_analysis.binaries,
    service_analysis.zipfiles,
    service_analysis.datas,
    tray_exe,
    tray_analysis.binaries,
    tray_analysis.zipfiles,
    tray_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WindowsFaceUnlock",
)
