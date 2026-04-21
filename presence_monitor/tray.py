from __future__ import annotations
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw
import pystray

from face_service.config import Config, LOG_PATH
from face_service.i18n import LANGUAGES, get_language, set_language, t

from .enroll_gui import open_enroll
from .gui import open_help, open_settings, open_status
from .monitor import PresenceMonitor, pipe_call

log = logging.getLogger(__name__)

SET_PASSWORD_CMD = ["-m", "tools.set_password"]

# Visual icons that sit after the label text in each tray menu entry.
# Placed at the end with a tab so they right-align nicely in the Windows
# context menu font. pystray does not support real per-item icons on
# Windows, so these emoji are the best we can do.
EMOJI = {
    "status":       "📊",
    "settings":     "⚙",
    "probe":        "📸",
    "pause":        "⏸",
    "resume":       "▶",
    "enroll":       "🧑",
    "set_password": "🔑",
    "open_log":     "📄",
    "language":     "🌐",
    "help":         "❓",
    "quit":         "⏻",
}


def _decorate(label: str, emoji_key: str) -> str:
    """Append a right-side emoji icon to the menu label."""
    return f"{label}\t{EMOJI.get(emoji_key, '')}"


def _icon_image(active: bool, paused: bool = False) -> Image.Image:
    img = Image.new("RGB", (64, 64), "white")
    d = ImageDraw.Draw(img)
    if paused:
        color = (200, 150, 30)
    elif active:
        color = (30, 130, 30)
    else:
        color = (130, 130, 130)
    d.ellipse((8, 8, 56, 56), outline=color, width=4)
    d.ellipse((22, 24, 28, 30), fill=color)
    d.ellipse((36, 24, 42, 30), fill=color)
    d.arc((20, 30, 44, 48), start=0, end=180, fill=color, width=3)
    return img


def _launch_tool(args: list[str]) -> None:
    """Spawn a tool in a new console window using the same Python that runs us."""
    repo_root = Path(__file__).resolve().parent.parent
    venv_py = repo_root / ".venv" / "Scripts" / "python.exe"
    py = str(venv_py) if venv_py.exists() else sys.executable
    try:
        subprocess.Popen(
            [py, *args],
            cwd=str(repo_root),
            creationflags=subprocess.CREATE_NEW_CONSOLE,  # type: ignore[attr-defined]
        )
    except Exception:
        log.exception("failed to launch tool: %s", args)


def _save_language(code: str) -> None:
    """Persist the language choice so it survives service restart."""
    try:
        cfg = Config.load()
        cfg.language = code
        cfg.validate()
        cfg.save()
    except Exception:
        log.exception("failed to persist language=%s", code)


def run_with_tray(cfg: Config) -> None:
    # Honor saved language from config.
    set_language(cfg.language)

    monitor = PresenceMonitor(cfg)
    thread = threading.Thread(target=monitor.run, name="presence-loop", daemon=True)
    thread.start()

    icon_ref: list[pystray.Icon] = []

    def refresh_icon() -> None:
        if not icon_ref:
            return
        icon = icon_ref[0]
        icon.icon = _icon_image(active=True, paused=monitor.is_paused())
        icon.title = t("tray.title")
        icon.update_menu()

    # ------------------------- actions ------------------------------------

    def on_toggle(icon, item):
        if monitor.is_paused():
            monitor.resume()
        else:
            monitor.pause()
        refresh_icon()

    def on_status(icon, item):
        open_status(monitor)

    def on_settings(icon, item):
        def on_saved(new_cfg: Config) -> None:
            monitor.reload_config(new_cfg)
            set_language(new_cfg.language)
            refresh_icon()
        open_settings(monitor, on_saved=on_saved)

    def on_help(icon, item):
        open_help()

    def on_enroll(icon, item):
        open_enroll()

    def on_set_password(icon, item):
        _launch_tool(SET_PASSWORD_CMD)

    def on_open_log(icon, item):
        try:
            os.startfile(str(LOG_PATH.parent))  # type: ignore[attr-defined]
        except Exception:
            log.exception("open log folder failed")

    def on_probe_now(icon, item):
        def _probe():
            resp = pipe_call({"cmd": "presence"}, timeout_s=10.0)
            log.info("manual probe: %s", resp)
        threading.Thread(target=_probe, daemon=True).start()

    def _stop_service_process() -> None:
        """Best-effort shutdown of face_service, then kill survivors."""
        try:
            pipe_call({"cmd": "shutdown"}, timeout_s=3.0)
        except Exception:
            pass
        time.sleep(1.0)
        try:
            import psutil  # type: ignore
            for p in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
                try:
                    cmdline = " ".join(p.info.get("cmdline") or [])
                except Exception:
                    continue
                name = (p.info.get("name") or "").lower()
                if name not in {"python.exe", "pythonw.exe"}:
                    continue
                if "face_service" in cmdline:
                    try:
                        log.info("terminating lingering face_service pid=%s", p.info["pid"])
                        p.terminate()
                    except Exception:
                        pass
        except Exception:
            log.exception("force-kill sweep failed")

    def on_quit(icon, item):
        log.info("Quit requested from tray")
        monitor.stop()
        threading.Thread(target=_stop_service_process, daemon=True).start()
        icon.stop()

    def make_language_handler(code: str):
        def _handler(icon, item):
            set_language(code)
            _save_language(code)
            # Propagate to the service too so presence_mode etc. use updated
            # config on next tick (reload is cheap; ignore failures).
            threading.Thread(
                target=lambda: pipe_call({"cmd": "reload_config"}, timeout_s=3.0),
                daemon=True,
            ).start()
            refresh_icon()
        return _handler

    def make_language_checked(code: str):
        return lambda item: get_language() == code

    # ------------------------- menu ----------------------------------------

    # All text callables so language switch rebuilds labels when the user
    # opens the menu next time.
    def lbl(key: str, emoji_key: str):
        return lambda item: _decorate(t(key), emoji_key)

    def pause_text(item):
        key = "tray.resume" if monitor.is_paused() else "tray.pause"
        icon = "resume" if monitor.is_paused() else "pause"
        return _decorate(t(key), icon)

    # Language submenu built from the LANGUAGES table. Each row is labelled
    # in its OWN language (native), so the label text is static — no need
    # for a t() callable here.
    language_items = tuple(
        pystray.MenuItem(
            text=f"{emoji}  {native}",
            action=make_language_handler(code),
            checked=make_language_checked(code),
            radio=True,
        )
        for code, native, emoji in LANGUAGES
    )
    language_submenu = pystray.Menu(*language_items)

    menu = pystray.Menu(
        pystray.MenuItem(lbl("tray.status", "status"), on_status),
        pystray.MenuItem(lbl("tray.settings", "settings"), on_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lbl("tray.probe", "probe"), on_probe_now),
        pystray.MenuItem(pause_text, on_toggle),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lbl("tray.enroll", "enroll"), on_enroll),
        pystray.MenuItem(lbl("tray.set_password", "set_password"), on_set_password),
        pystray.MenuItem(lbl("tray.open_log", "open_log"), on_open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lbl("tray.language", "language"), language_submenu),
        pystray.MenuItem(lbl("tray.help", "help"), on_help),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lbl("tray.quit", "quit"), on_quit),
    )

    icon = pystray.Icon(
        "face-unlock-presence",
        _icon_image(active=True, paused=False),
        t("tray.title"),
        menu,
    )
    icon_ref.append(icon)
    icon.run()
