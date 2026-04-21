"""Named pipe server exposing face verification + credential retrieval.

Protocol: line-delimited JSON.  Client sends {"cmd": "...", ...}, server replies
with a single JSON line and closes the connection.

Commands:
  {"cmd":"ping"}
      -> {"ok":true,"pong":true}
  {"cmd":"verify"}
      -> {"ok":true,"match":bool,"distance":float,"real":bool}
  {"cmd":"unlock"}             # verify + return credentials on success
      -> {"ok":true,"username":"...","password":"...","domain":"..."}  (on match)
      -> {"ok":false,"reason":"..."}
  {"cmd":"presence"}           # single-frame presence probe
      -> {"ok":true,"present":bool,"real":bool,"mode":"recognition|detection"}
  {"cmd":"status"}             # service metadata for GUI
      -> {"ok":true,"uptime_s":float,"config":{...},"enrollment":bool}
  {"cmd":"reload_config"}      # re-read config.toml from disk
      -> {"ok":true,"config":{...}}
  {"cmd":"pause_camera","seconds":120}   # release webcam for N seconds so
                                          # the enrollment GUI can own it
      -> {"ok":true,"paused_until":float}
  {"cmd":"resume_camera"}                 # clear the camera lease early
      -> {"ok":true}
  {"cmd":"build_enrollment"}              # (re)compute embeddings from ENROLL_DIR
      -> {"ok":true,"count":int} | {"ok":false,"reason":str}
  {"cmd":"shutdown"}           # stop the service cleanly (tray Quit uses this)
      -> {"ok":true,"shutting_down":true}
"""
from __future__ import annotations
import json
import logging
import threading
import time
from dataclasses import asdict
from typing import Callable

import pywintypes  # type: ignore
import win32api  # type: ignore
import win32file  # type: ignore
import win32pipe  # type: ignore
import win32security  # type: ignore


def win32api_get_last_error() -> int:
    return win32api.GetLastError()

from .camera import Camera
from .config import Config, LOG_PATH, PIPE_NAME
from .credentials import load_password
from .detector import FaceDetector
from .recognizer import Recognizer

log = logging.getLogger(__name__)


def _build_sa_everyone() -> win32security.SECURITY_ATTRIBUTES:
    """Allow LogonUI (SYSTEM) and any logged-in user to connect to the pipe."""
    sd = win32security.SECURITY_DESCRIPTOR()
    sd.SetSecurityDescriptorDacl(1, None, 0)  # NULL DACL = allow all (OK for named pipe on localhost)
    sa = win32security.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    sa.bInheritHandle = 0
    return sa


class FaceService:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.recog = Recognizer(cfg)
        self.detector = FaceDetector()
        self._stop = threading.Event()
        self._cam_lock = threading.Lock()
        self._cam: Camera | None = None  # kept open when persistent_camera=True
        self._started_at = time.time()
        # When the enrollment wizard is running it needs exclusive access to
        # the webcam. ``_camera_paused_until`` holds an epoch timestamp: probes
        # and verify calls short-circuit until that time passes. The service
        # also releases the persistent camera so the tray can open it.
        self._camera_paused_until: float = 0.0

    def _camera_leased_out(self) -> bool:
        return time.time() < self._camera_paused_until

    def _get_camera(self) -> Camera:
        """Return the shared persistent camera, opening it if needed."""
        if self._cam is None:
            self._cam = Camera(self.cfg.camera_index, self.cfg.camera_warmup_frames)
            self._cam.open()
        return self._cam

    def _release_camera(self) -> None:
        if self._cam is not None:
            self._cam.close()
            self._cam = None

    # ---------- core ops ----------

    def _capture_and_verify(self) -> tuple[bool, float, bool]:
        if self._camera_leased_out():
            log.info("verify skipped: camera leased out to enrollment")
            return False, 1.0, False
        matches = 0
        best = 1.0
        real_seen = False
        with self._cam_lock:
            cam = self._get_camera() if self.cfg.persistent_camera else Camera(
                self.cfg.camera_index, self.cfg.camera_warmup_frames
            )
            if not self.cfg.persistent_camera:
                cam.open()
            try:
                # drain stale buffered frames
                for _ in range(2):
                    cam.read()
                for _ in range(self.cfg.verify_frames):
                    frame = cam.read()
                    if frame is None:
                        continue
                    try:
                        ok, dist, real = self.recog.verify_frame(frame)
                    except Exception as e:
                        log.warning("verify error: %s", e)
                        continue
                    real_seen = real_seen or real
                    if dist < best:
                        best = dist
                    if ok:
                        matches += 1
                        if matches >= self.cfg.verify_required:
                            return True, best, True
            finally:
                if not self.cfg.persistent_camera:
                    cam.close()
        return False, best, real_seen

    def _presence_probe(self) -> tuple[bool, bool]:
        """(present, real) — semantics depend on config.presence_mode.

        recognition: ``present`` = enrolled face detected AND passes anti-spoofing.
        detection:   ``present`` = *any* face detected by YuNet. ``real`` is
                     reported as True (anti-spoofing not evaluated).
        """
        if self._camera_leased_out():
            log.info("presence probe skipped: camera leased out to enrollment")
            # Return (True, True) so the monitor doesn't rack up strikes
            # while the user is enrolling their face.
            return True, True
        if self.cfg.presence_mode == "detection":
            return self._presence_probe_detection()
        return self._presence_probe_recognition()

    def _presence_probe_recognition(self) -> tuple[bool, bool]:
        with self._cam_lock:
            cam = self._get_camera() if self.cfg.persistent_camera else Camera(
                self.cfg.camera_index, self.cfg.camera_warmup_frames
            )
            if not self.cfg.persistent_camera:
                cam.open()
            try:
                for _ in range(2):
                    cam.read()
                for _ in range(3):
                    frame = cam.read()
                    if frame is None:
                        continue
                    try:
                        ok, _dist, real = self.recog.verify_frame(frame)
                    except Exception:
                        continue
                    if ok:
                        return True, real
            finally:
                if not self.cfg.persistent_camera:
                    cam.close()
        return False, False

    def _presence_probe_detection(self) -> tuple[bool, bool]:
        with self._cam_lock:
            cam = self._get_camera() if self.cfg.persistent_camera else Camera(
                self.cfg.camera_index, self.cfg.camera_warmup_frames
            )
            if not self.cfg.persistent_camera:
                cam.open()
            try:
                for _ in range(2):
                    cam.read()
                for _ in range(5):
                    frame = cam.read()
                    if frame is None:
                        continue
                    try:
                        if self.detector.has_face(frame):
                            return True, True
                    except Exception as e:
                        log.warning("detector error: %s", e)
                        continue
            finally:
                if not self.cfg.persistent_camera:
                    cam.close()
        return False, True

    # ---------- pipe ----------

    def _status(self) -> dict:
        from .config import EMBED_PATH
        return {
            "ok": True,
            "uptime_s": time.time() - self._started_at,
            "config": asdict(self.cfg),
            "enrollment": EMBED_PATH.exists(),
        }

    def _reload_config(self) -> dict:
        new_cfg = Config.load()
        try:
            new_cfg.validate()
        except ValueError as e:
            return {"ok": False, "reason": f"invalid-config: {e}"}
        old_index = self.cfg.camera_index
        old_persistent = self.cfg.persistent_camera
        self.cfg = new_cfg
        self.recog.cfg = new_cfg
        # Reset camera if camera-affecting settings changed
        if new_cfg.camera_index != old_index or new_cfg.persistent_camera != old_persistent:
            with self._cam_lock:
                self._release_camera()
        return {"ok": True, "config": asdict(new_cfg)}

    def _handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "ping":
            return {"ok": True, "pong": True}

        if cmd == "status":
            return self._status()

        if cmd == "reload_config":
            return self._reload_config()

        if cmd == "shutdown":
            log.info("shutdown requested via pipe")
            self._stop.set()
            return {"ok": True, "shutting_down": True}

        if cmd == "pause_camera":
            # Release the webcam and ignore probe/verify for the requested
            # number of seconds so the enrollment wizard can own it.
            seconds = float(req.get("seconds", 120))
            self._camera_paused_until = time.time() + max(5.0, seconds)
            with self._cam_lock:
                self._release_camera()
            log.info("camera leased out for %.0fs (enrollment)", seconds)
            return {"ok": True, "paused_until": self._camera_paused_until}

        if cmd == "resume_camera":
            was = self._camera_paused_until
            self._camera_paused_until = 0.0
            log.info("camera lease cleared (was until %s)", was)
            return {"ok": True}

        if cmd == "build_enrollment":
            try:
                from .config import ENROLL_DIR
                n = self.recog.enroll_from_dir(ENROLL_DIR)
                return {"ok": True, "count": n}
            except Exception as e:
                log.exception("build_enrollment failed")
                return {"ok": False, "reason": str(e)}

        if cmd == "verify":
            ok, dist, real = self._capture_and_verify()
            return {"ok": True, "match": ok, "distance": dist, "real": real}

        if cmd == "presence":
            present, real = self._presence_probe()
            return {"ok": True, "present": present, "real": real, "mode": self.cfg.presence_mode}

        if cmd == "unlock":
            ok, dist, real = self._capture_and_verify()
            if not ok:
                return {"ok": False, "reason": "no-match", "distance": dist, "real": real}
            creds = load_password()
            if not creds:
                return {"ok": False, "reason": "no-credentials"}
            return {
                "ok": True,
                "username": creds["u"],
                "password": creds["p"],
                "domain": creds.get("d", "."),
            }

        return {"ok": False, "reason": "unknown-command"}

    def _serve_one(self) -> None:
        sa = _build_sa_everyone()
        handle = win32pipe.CreateNamedPipe(
            PIPE_NAME,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            65536, 65536, 0, sa,
        )
        try:
            win32pipe.ConnectNamedPipe(handle, None)
            _hr, data = win32file.ReadFile(handle, 65536)
            req = json.loads(data.decode("utf-8"))
            log.info("request cmd=%s", req.get("cmd"))
            try:
                resp = self._handle(req)
            except Exception as e:
                log.exception("handler error")
                resp = {"ok": False, "reason": f"exception: {e}"}
            win32file.WriteFile(handle, (json.dumps(resp) + "\n").encode("utf-8"))
            try:
                win32file.FlushFileBuffers(handle)
            except pywintypes.error:
                pass
        finally:
            try:
                win32pipe.DisconnectNamedPipe(handle)
            except pywintypes.error:
                pass
            win32file.CloseHandle(handle)

    def _warmup(self) -> None:
        """Load enrollment, preload heavy models so the first real call is fast."""
        import numpy as np
        try:
            self.recog.load()
            log.info("enrollment loaded: %s", self.recog._refs is not None)
        except Exception as e:
            log.warning("enrollment load: %s", e)

        # Force-load ArcFace + detector + MiniFASNet with a dummy image.
        # Using one of our enrolled photos guarantees a face is present.
        try:
            from .config import ENROLL_DIR
            import cv2
            enroll_imgs = list(ENROLL_DIR.glob("*.jpg")) + list(ENROLL_DIR.glob("*.png"))
            if enroll_imgs:
                img = cv2.imread(str(enroll_imgs[0]))
                if img is not None:
                    t0 = time.time()
                    self.recog.verify_frame(img)
                    log.info("model warmup ok in %.2fs", time.time() - t0)
        except Exception as e:
            log.warning("model warmup failed: %s", e)

        # Also warm up the camera (open + close if not persistent)
        try:
            cam = self._get_camera()
            cam.read()
            log.info("camera warmup ok (persistent=%s)", self.cfg.persistent_camera)
            if not self.cfg.persistent_camera:
                self._release_camera()
        except Exception as e:
            log.warning("camera warmup failed: %s", e)

    def serve_forever(self) -> None:
        import win32event  # type: ignore
        import winerror    # type: ignore
        # Single-instance guard: if another FaceService is already serving
        # this pipe, bail out cleanly instead of competing for connections.
        try:
            mutex = win32event.CreateMutex(None, False, "Local\\FaceUnlockService")
            if win32api_get_last_error() == winerror.ERROR_ALREADY_EXISTS:
                log.warning("another FaceService instance already running; exiting")
                return
        except Exception as e:
            log.warning("mutex check failed, continuing: %s", e)

        log.info("FaceService starting; pipe=%s", PIPE_NAME)
        if self.cfg.warmup_on_start:
            self._warmup()

        while not self._stop.is_set():
            try:
                self._serve_one()
            except Exception:
                log.exception("pipe error")
                time.sleep(0.5)

        log.info("FaceService stopped")
        with self._cam_lock:
            self._release_camera()

    def stop(self) -> None:
        self._stop.set()


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )


def main() -> None:
    _setup_logging()
    cfg = Config.load()
    svc = FaceService(cfg)
    try:
        svc.serve_forever()
    except KeyboardInterrupt:
        svc.stop()


if __name__ == "__main__":
    main()
