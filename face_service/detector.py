"""Lightweight YuNet face *detector* (not recognizer).

Used by presence-mode ``detection``: the old AutoFaceLock behaviour where any
human face in front of the camera is enough to stay unlocked — no DeepFace,
no enrollment match. Cheap and fast; no TensorFlow/torch needed.
"""
from __future__ import annotations
import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUNDLED_MODEL = _REPO_ROOT / "models" / "face_detection_yunet_2023mar.onnx"
_LEGACY_MODEL = Path(
    r"C:\Program Files\facewinunlock-tauri\resources\face_detection_yunet_2023mar.onnx"
)


def yunet_model_path() -> Path:
    if _BUNDLED_MODEL.exists():
        return _BUNDLED_MODEL
    if _LEGACY_MODEL.exists():
        return _LEGACY_MODEL
    raise FileNotFoundError(
        f"YuNet model not found. Expected at {_BUNDLED_MODEL} or {_LEGACY_MODEL}."
    )


class FaceDetector:
    """Any-face detector backed by OpenCV's YuNet."""

    def __init__(
        self,
        score_threshold: float = 0.7,
        nms_threshold: float = 0.3,
        top_k: int = 50,
    ):
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.top_k = top_k
        self._impl: cv2.FaceDetectorYN | None = None
        self._size: tuple[int, int] | None = None

    def _ensure(self, width: int, height: int) -> cv2.FaceDetectorYN:
        if self._impl is None:
            self._impl = cv2.FaceDetectorYN.create(
                str(yunet_model_path()),
                "",
                (width, height),
                self.score_threshold,
                self.nms_threshold,
                self.top_k,
            )
            self._size = (width, height)
        elif self._size != (width, height):
            self._impl.setInputSize((width, height))
            self._size = (width, height)
        return self._impl

    def has_face(self, bgr: np.ndarray) -> bool:
        h, w = bgr.shape[:2]
        det = self._ensure(w, h)
        _, faces = det.detect(bgr)
        return faces is not None and len(faces) > 0
