from __future__ import annotations
import time
import cv2
import numpy as np


class Camera:
    """Thin wrapper over cv2.VideoCapture with open/close safety."""

    def __init__(self, index: int = 0, warmup_frames: int = 10):
        self.index = index
        self.warmup_frames = warmup_frames
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        if self._cap is not None:
            return
        last_err: str | None = None
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            cap = cv2.VideoCapture(self.index, backend)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # don't accumulate stale frames
            ok = False
            for _ in range(5):
                ret, _ = cap.read()
                if ret:
                    ok = True
                    break
                time.sleep(0.1)
            if ok:
                self._cap = cap
                # auto-exposure warm-up (lock screen lighting can be dim)
                for _ in range(self.warmup_frames):
                    cap.read()
                    time.sleep(0.03)
                return
            last_err = f"backend={backend} isOpened={cap.isOpened()}"
            cap.release()
        raise RuntimeError(f"Cannot open camera index {self.index} ({last_err})")

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read(self) -> np.ndarray | None:
        assert self._cap is not None, "Camera not opened"
        ok, frame = self._cap.read()
        return frame if ok else None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
