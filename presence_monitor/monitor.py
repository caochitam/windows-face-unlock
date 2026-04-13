from __future__ import annotations
import json
import logging
import threading
import time

import ctypes
import pywintypes  # type: ignore
import win32file  # type: ignore

from face_service.config import Config, PIPE_NAME

from .remote_session import is_remote_context

log = logging.getLogger(__name__)


def _lock_workstation() -> None:
    ctypes.windll.user32.LockWorkStation()


def _get_idle_seconds() -> float:
    """Seconds since last user input (keyboard/mouse)."""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    tick = ctypes.windll.kernel32.GetTickCount()
    return (tick - lii.dwTime) / 1000.0


def _pipe_call(req: dict, timeout_s: float = 30.0) -> dict | None:
    """Send a JSON request to the FaceService pipe and return the response."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            handle = win32file.CreateFile(
                PIPE_NAME,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None,
            )
            break
        except pywintypes.error:
            time.sleep(0.2)
    else:
        log.warning("FaceService pipe not available")
        return None

    try:
        win32file.WriteFile(handle, (json.dumps(req) + "\n").encode("utf-8"))
        _hr, data = win32file.ReadFile(handle, 65536)
        return json.loads(data.decode("utf-8").strip())
    except Exception as e:
        log.warning("pipe call failed: %s", e)
        return None
    finally:
        try:
            win32file.CloseHandle(handle)
        except Exception:
            pass


class PresenceMonitor:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._strikes = 0

    def pause(self) -> None:
        self._paused.set()
        log.info("presence monitor paused")

    def resume(self) -> None:
        self._paused.clear()
        self._strikes = 0
        log.info("presence monitor resumed")

    def is_paused(self) -> bool:
        return self._paused.is_set()

    def stop(self) -> None:
        self._stop.set()

    def _tick(self) -> None:
        # 1. Skip if paused from the tray
        if self._paused.is_set():
            return

        # 2. Skip if this is a remote session — face check doesn't make sense
        #    when nobody is physically at the machine.
        remote, reason = is_remote_context()
        if remote:
            log.info("skip: remote context (%s)", reason)
            self._strikes = 0
            return

        # NOTE: We deliberately do NOT skip based on keyboard/mouse input.
        # The goal is pure face-based presence: if the enrolled face is not
        # in front of the camera, lock — even if someone else is actively
        # using the machine (stronger "walk-away" security).

        # 3. Probe camera via FaceService
        resp = _pipe_call({"cmd": "presence"}, timeout_s=20.0)
        if resp is None:
            # Service down — don't lock blindly
            log.warning("presence probe: service unavailable; skipping")
            return

        present = bool(resp.get("present"))
        log.info("presence probe: present=%s real=%s", present, resp.get("real"))

        if present:
            self._strikes = 0
            return

        self._strikes += 1
        if self._strikes >= self.cfg.presence_absent_strikes:
            log.warning("absent %d ticks — locking workstation", self._strikes)
            self._strikes = 0
            _lock_workstation()

    def run(self) -> None:
        log.info("presence monitor loop: interval=%ss strikes=%s",
                 self.cfg.presence_interval_s, self.cfg.presence_absent_strikes)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("tick error")
            # wake up sooner if stop is signalled
            self._stop.wait(self.cfg.presence_interval_s)


def main() -> None:
    from face_service.config import LOG_PATH
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH.with_name("presence.log"), encoding="utf-8"),
                  logging.StreamHandler()],
    )
    cfg = Config.load()
    from .tray import run_with_tray
    run_with_tray(cfg)


if __name__ == "__main__":
    main()
