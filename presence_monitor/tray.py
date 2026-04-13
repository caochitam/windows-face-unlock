from __future__ import annotations
import logging
import threading

from PIL import Image, ImageDraw
import pystray

from face_service.config import Config
from .monitor import PresenceMonitor

log = logging.getLogger(__name__)


def _icon_image(active: bool) -> Image.Image:
    img = Image.new("RGB", (64, 64), "white")
    d = ImageDraw.Draw(img)
    color = (30, 130, 30) if active else (130, 130, 130)
    d.ellipse((8, 8, 56, 56), outline=color, width=4)
    d.ellipse((22, 24, 28, 30), fill=color)
    d.ellipse((36, 24, 42, 30), fill=color)
    d.arc((20, 30, 44, 48), start=0, end=180, fill=color, width=3)
    return img


def run_with_tray(cfg: Config) -> None:
    monitor = PresenceMonitor(cfg)
    thread = threading.Thread(target=monitor.run, name="presence-loop", daemon=True)
    thread.start()

    icon_ref: list[pystray.Icon] = []

    def on_toggle(icon, item):
        if monitor.is_paused():
            monitor.resume()
        else:
            monitor.pause()
        icon.icon = _icon_image(not monitor.is_paused())
        icon.update_menu()

    def on_quit(icon, item):
        monitor.stop()
        icon.stop()

    def paused_text(item):
        return "Resume" if monitor.is_paused() else "Pause"

    menu = pystray.Menu(
        pystray.MenuItem(paused_text, on_toggle),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("face-unlock-presence", _icon_image(True), "Face Unlock — Presence", menu)
    icon_ref.append(icon)
    icon.run()
