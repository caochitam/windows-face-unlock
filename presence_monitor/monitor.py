from __future__ import annotations
import json
import logging
import threading
import time
from dataclasses import dataclass, field

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


def pipe_call(req: dict, timeout_s: float = 30.0) -> dict | None:
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


# Backwards-compat alias
_pipe_call = pipe_call


@dataclass
class TickSnapshot:
    at: float = 0.0
    result: str = "-"       # present / absent / skipped / error
    reason: str = ""
    strikes: int = 0
    mode: str = ""


class PresenceMonitor:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._strikes = 0
        self._last = TickSnapshot()
        self._lock_count = 0
        self._state_lock = threading.Lock()

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

    def reload_config(self, cfg: Config) -> None:
        self.cfg = cfg
        self._strikes = 0
        log.info(
            "presence monitor config reloaded: interval=%ss strikes=%s mode=%s",
            cfg.presence_interval_s, cfg.presence_absent_strikes, cfg.presence_mode,
        )

    def snapshot(self) -> dict:
        with self._state_lock:
            last = self._last
            return {
                "paused": self._paused.is_set(),
                "strikes": self._strikes,
                "lock_count": self._lock_count,
                "last_at": last.at,
                "last_result": last.result,
                "last_reason": last.reason,
                "last_mode": last.mode,
                "interval_s": self.cfg.presence_interval_s,
                "absent_strikes": self.cfg.presence_absent_strikes,
                "mode": self.cfg.presence_mode,
            }

    def _set_last(self, result: str, reason: str = "", mode: str = "") -> None:
        with self._state_lock:
            self._last = TickSnapshot(
                at=time.time(),
                result=result,
                reason=reason,
                strikes=self._strikes,
                mode=mode or self.cfg.presence_mode,
            )

    def _tick(self) -> None:
        # 1. Skip if paused from the tray
        if self._paused.is_set():
            self._set_last("skipped", "paused")
            return

        # 2. Skip if this is a remote session — face check doesn't make sense
        #    when nobody is physically at the machine.
        remote, reason = is_remote_context()
        if remote:
            log.info("skip: remote context (%s)", reason)
            self._strikes = 0
            self._set_last("skipped", reason)
            return

        # NOTE: We deliberately do NOT skip based on keyboard/mouse input.
        # The goal is pure face-based presence: if the enrolled face is not
        # in front of the camera, lock — even if someone else is actively
        # using the machine (stronger "walk-away" security).

        # 3. Probe camera via FaceService
        resp = pipe_call({"cmd": "presence"}, timeout_s=20.0)
        if resp is None:
            # Service down — don't lock blindly
            log.warning("presence probe: service unavailable; skipping")
            self._set_last("error", "service-unavailable")
            return

        present = bool(resp.get("present"))
        mode = resp.get("mode", self.cfg.presence_mode)
        log.info("presence probe: present=%s real=%s mode=%s",
                 present, resp.get("real"), mode)

        if present:
            self._strikes = 0
            self._set_last("present", f"real={resp.get('real')}", mode)
            return

        self._strikes += 1
        self._set_last("absent", f"strike {self._strikes}/{self.cfg.presence_absent_strikes}", mode)
        if self._strikes >= self.cfg.presence_absent_strikes:
            log.warning("absent %d ticks — locking workstation", self._strikes)
            self._strikes = 0
            with self._state_lock:
                self._lock_count += 1
            _lock_workstation()

    def run(self) -> None:
        log.info("presence monitor loop: interval=%ss strikes=%s mode=%s",
                 self.cfg.presence_interval_s,
                 self.cfg.presence_absent_strikes,
                 self.cfg.presence_mode)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("tick error")
                self._set_last("error", "exception")
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
