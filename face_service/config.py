from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

APP_DIR = Path(os.environ.get("FACE_UNLOCK_HOME", Path.home() / ".face-unlock"))
CONFIG_PATH = APP_DIR / "config.toml"
ENROLL_DIR = APP_DIR / "enroll"
EMBED_PATH = APP_DIR / "embeddings.npz"
CREDS_PATH = APP_DIR / "credentials.bin"
LOG_PATH = APP_DIR / "service.log"

PIPE_NAME = r"\\.\pipe\FaceUnlock"


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
    warmup_on_start: bool = True

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            APP_DIR.mkdir(parents=True, exist_ok=True)
            return cls()
        data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
