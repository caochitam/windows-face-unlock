from __future__ import annotations
import os
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

try:
    import tomli_w  # type: ignore
except ImportError:  # pragma: no cover - optional for read-only usage
    tomli_w = None  # type: ignore

APP_DIR = Path(os.environ.get("FACE_UNLOCK_HOME", Path.home() / ".face-unlock"))
CONFIG_PATH = APP_DIR / "config.toml"
ENROLL_DIR = APP_DIR / "enroll"
EMBED_PATH = APP_DIR / "embeddings.npz"
CREDS_PATH = APP_DIR / "credentials.bin"
LOG_PATH = APP_DIR / "service.log"

PIPE_NAME = r"\\.\pipe\FaceUnlock"

PRESENCE_MODES = ("recognition", "detection")


def _default_language() -> str:
    # Imported here to avoid a circular import (i18n → config is fine,
    # but we only need the detection helper at runtime).
    from .i18n import detect_system_language
    return detect_system_language()


@dataclass
class Config:
    model_name: str = "ArcFace"
    detector_backend: str = "yunet"  # yunet is fast + robust. Alternatives: opencv, retinaface
    distance_metric: str = "cosine"
    threshold: float = 0.45          # ArcFace cosine
    anti_spoofing: bool = True
    camera_index: int = 0
    camera_warmup_frames: int = 10   # discard N frames after opening for auto-exposure
    persistent_camera: bool = True   # keep VideoCapture open between requests
    verify_frames: int = 5            # số frame cần đạt ngưỡng
    verify_required: int = 2          # trong đó cần ≥ N khớp (giảm từ 3 để nhanh hơn)
    presence_interval_s: int = 60
    presence_absent_strikes: int = 2  # vắng mặt liên tiếp trước khi lock
    # "recognition" = DeepFace ArcFace must match enrolled face (stronger; walk-away + strangers)
    # "detection"   = YuNet any-face-in-frame is enough (weaker; mimics old AutoFaceLock)
    presence_mode: str = "recognition"
    warmup_on_start: bool = True
    # UI language code (see face_service.i18n.LANGUAGES). Auto-detected
    # from the system locale on first run if the config file is missing.
    language: str = field(default_factory=_default_language)

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            APP_DIR.mkdir(parents=True, exist_ok=True)
            return cls()
        data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self) -> None:
        if tomli_w is None:
            raise RuntimeError("tomli-w is required to save config (pip install tomli-w)")
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            tomli_w.dumps(asdict(self)),
            encoding="utf-8",
        )

    def validate(self) -> None:
        from .i18n import LANG_CODES
        if self.presence_mode not in PRESENCE_MODES:
            raise ValueError(
                f"presence_mode must be one of {PRESENCE_MODES}, got {self.presence_mode!r}"
            )
        if self.presence_interval_s < 5:
            raise ValueError("presence_interval_s must be >= 5")
        if self.presence_absent_strikes < 1:
            raise ValueError("presence_absent_strikes must be >= 1")
        if not (0.0 < self.threshold < 2.0):
            raise ValueError("threshold must be in (0, 2)")
        if self.language not in LANG_CODES:
            raise ValueError(
                f"language must be one of {LANG_CODES}, got {self.language!r}"
            )
