"""Tkinter management windows — Status + Settings + Help.

Runs in the same process as the tray, launched from its menu. Kept in the
tray process (not the service) so Settings can reach both: local
PresenceMonitor state, and the FaceService over the pipe.

Every field has a small ⓘ button whose click shows a messagebox with the
localised description, and whose hover shows the same text as a tooltip.
"""
from __future__ import annotations
import logging
import threading
import time
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Callable

from face_service.config import Config, CONFIG_PATH, LOG_PATH, PRESENCE_MODES
from face_service.i18n import LANGUAGES, get_language, set_language, t

from .monitor import PresenceMonitor, pipe_call
from .widgets import InfoButton, Tooltip, attach_tooltip

log = logging.getLogger(__name__)


def _format_age(ts: float) -> str:
    if ts <= 0:
        return t("status.val.never")
    age = int(time.time() - ts)
    if age < 60:
        return t("status.age.seconds", n=age)
    if age < 3600:
        return t("status.age.minutes", m=age // 60, s=age % 60)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


# (i18n_key, snapshot_key_or_callable) for Status window rows.
STATUS_ROWS = [
    ("status.service",    "svc"),
    ("status.uptime",     "uptime"),
    ("status.mode",       "mode"),
    ("status.last",       "last"),
    ("status.result",     "result"),
    ("status.reason",     "reason"),
    ("status.strikes",    "strikes"),
    ("status.lock_count", "locks"),
    ("status.paused",     "paused"),
    ("status.enrollment", "enroll"),
]

STATUS_BUTTONS = [
    ("status.btn.ping",     "_ping"),
    ("status.btn.probe",    "_probe"),
    ("status.btn.open_log", "_open_logs"),
    ("status.btn.close",    "_close"),
]


class StatusWindow:
    """Read-only status dashboard. Polls every 2s."""

    def __init__(self, monitor: PresenceMonitor):
        self.monitor = monitor
        self.root = tk.Tk()
        self.root.title(t("status.title"))
        self.root.geometry("560x480")
        self._build()
        self._refresh_loop()

    def _build(self) -> None:
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        self.vars: dict[str, tk.StringVar] = {}
        for i, (label_key, key) in enumerate(STATUS_ROWS):
            ttk.Label(frm, text=t(label_key) + ":", width=18, anchor="e").grid(
                row=i, column=0, sticky="e", padx=4, pady=2
            )
            v = tk.StringVar(value="—")
            self.vars[key] = v
            ttk.Label(frm, textvariable=v, anchor="w").grid(
                row=i, column=1, sticky="we", padx=4, pady=2
            )
            ib = InfoButton(frm, i18n_key=label_key + ".desc")
            ib.grid(row=i, column=2, sticky="w", padx=4, pady=2)

        frm.columnconfigure(1, weight=1)

        ttk.Separator(frm).grid(
            row=len(STATUS_ROWS), column=0, columnspan=3, sticky="we", pady=8
        )

        btns = ttk.Frame(frm)
        btns.grid(row=len(STATUS_ROWS) + 1, column=0, columnspan=3, sticky="we")
        for label_key, method_name in STATUS_BUTTONS[:-1]:
            b = ttk.Button(btns, text=t(label_key), command=getattr(self, method_name))
            b.pack(side="left", padx=4)
            attach_tooltip(b, label_key + ".desc")
        close_label, close_method = STATUS_BUTTONS[-1]
        close_btn = ttk.Button(btns, text=t(close_label), command=getattr(self, close_method))
        close_btn.pack(side="right", padx=4)
        attach_tooltip(close_btn, close_label + ".desc")

    def _refresh_loop(self) -> None:
        try:
            self._refresh()
        finally:
            self.root.after(2000, self._refresh_loop)

    def _refresh(self) -> None:
        snap = self.monitor.snapshot()
        status = pipe_call({"cmd": "status"}, timeout_s=2.0)

        if status and status.get("ok"):
            self.vars["svc"].set(t("status.val.running"))
            self.vars["uptime"].set(f"{status['uptime_s']:.0f}s")
            self.vars["enroll"].set(
                t("status.val.yes") if status.get("enrollment") else t("status.val.no")
            )
        else:
            self.vars["svc"].set(t("status.val.not_reachable"))
            self.vars["uptime"].set("—")
            self.vars["enroll"].set("—")

        self.vars["mode"].set(snap.get("last_mode") or snap.get("mode") or "—")
        self.vars["last"].set(_format_age(snap.get("last_at", 0)))
        self.vars["result"].set(snap.get("last_result", "—"))
        self.vars["reason"].set(snap.get("last_reason", "") or "—")
        self.vars["strikes"].set(
            f"{snap.get('strikes', 0)} / {snap.get('absent_strikes', 0)}"
        )
        self.vars["locks"].set(str(snap.get("lock_count", 0)))
        self.vars["paused"].set(
            t("status.val.yes") if snap.get("paused") else t("status.val.no")
        )

    def _ping(self) -> None:
        resp = pipe_call({"cmd": "ping"}, timeout_s=3.0)
        if resp and resp.get("ok"):
            messagebox.showinfo(t("status.btn.ping"), "pong", parent=self.root)
        else:
            messagebox.showwarning(t("status.btn.ping"), t("status.val.not_reachable"), parent=self.root)

    def _probe(self) -> None:
        resp = pipe_call({"cmd": "presence"}, timeout_s=10.0)
        if resp and resp.get("ok"):
            messagebox.showinfo(
                t("status.btn.probe"),
                f"present={resp.get('present')} real={resp.get('real')} mode={resp.get('mode')}",
                parent=self.root,
            )
        else:
            messagebox.showwarning(t("status.btn.probe"), t("status.val.not_reachable"), parent=self.root)

    def _open_logs(self) -> None:
        import os
        os.startfile(str(LOG_PATH.parent))  # type: ignore[attr-defined]

    def _close(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


# (field_name, widget_kind, extras) — the label + .desc keys come from i18n.
SETTINGS_FIELDS: list[tuple[str, str, object]] = [
    ("language",                  "combo_lang", None),
    ("presence_mode",             "combo",      PRESENCE_MODES),
    ("presence_interval_s",       "int",        (5, 3600)),
    ("presence_absent_strikes",   "int",        (1, 20)),
    ("threshold",                 "float",      (0.05, 1.5)),
    ("verify_frames",             "int",        (1, 30)),
    ("verify_required",           "int",        (1, 30)),
    ("anti_spoofing",             "bool",       None),
    ("camera_index",              "int",        (0, 10)),
    ("camera_warmup_frames",      "int",        (0, 60)),
    ("persistent_camera",         "bool",       None),
    ("warmup_on_start",           "bool",       None),
]


class SettingsWindow:
    def __init__(
        self,
        monitor: PresenceMonitor,
        on_saved: Callable[[Config], None] | None = None,
    ):
        self.monitor = monitor
        self.on_saved = on_saved
        self.root = tk.Tk()
        self.root.title(t("settings.title"))
        self.root.geometry("620x620")
        self.cfg = Config.load()
        self.widgets: dict[str, tuple[str, tk.Variable]] = {}
        self._build()

    def _build(self) -> None:
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text=t("settings.editing", path=str(CONFIG_PATH)),
            foreground="#555",
            wraplength=560,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        for i, (name, kind, extras) in enumerate(SETTINGS_FIELDS, start=1):
            current = getattr(self.cfg, name)
            label_key = f"field.{name}"
            ttk.Label(frm, text=t(label_key) + ":", anchor="e", width=30).grid(
                row=i, column=0, sticky="e", padx=4, pady=3
            )
            var: tk.Variable
            if kind == "bool":
                var = tk.BooleanVar(value=bool(current))
                w: tk.Widget = ttk.Checkbutton(frm, variable=var)
            elif kind == "combo":
                var = tk.StringVar(value=str(current))
                w = ttk.Combobox(
                    frm, textvariable=var, values=list(extras or ()),
                    state="readonly", width=22,
                )
            elif kind == "combo_lang":
                var = tk.StringVar()
                code_to_display = {
                    code: f"{emoji}  {name_}" for code, name_, emoji in LANGUAGES
                }
                display_to_code = {v: k for k, v in code_to_display.items()}
                var.set(code_to_display.get(str(current), str(current)))
                w = ttk.Combobox(
                    frm, textvariable=var, values=list(code_to_display.values()),
                    state="readonly", width=22,
                )
                # Store the reverse map on the widget for _collect.
                w._lang_display_to_code = display_to_code  # type: ignore[attr-defined]
            elif kind == "int":
                lo, hi = extras  # type: ignore[misc]
                var = tk.IntVar(value=int(current))
                w = ttk.Spinbox(frm, from_=lo, to=hi, textvariable=var, width=10)
            elif kind == "float":
                lo, hi = extras  # type: ignore[misc]
                var = tk.DoubleVar(value=float(current))
                w = ttk.Spinbox(
                    frm, from_=lo, to=hi, increment=0.01,
                    textvariable=var, width=10, format="%.3f",
                )
            else:
                continue
            w.grid(row=i, column=1, sticky="w", padx=4, pady=3)

            ib = InfoButton(frm, i18n_key=label_key + ".desc")
            ib.grid(row=i, column=2, sticky="w", padx=4, pady=3)

            # Also tooltip the input widget itself.
            attach_tooltip(w, label_key + ".desc")

            self.widgets[name] = (kind, var)

        frm.columnconfigure(1, weight=1)

        ttk.Separator(frm).grid(
            row=len(SETTINGS_FIELDS) + 1, column=0, columnspan=3, sticky="we", pady=10
        )

        btns = ttk.Frame(frm)
        btns.grid(row=len(SETTINGS_FIELDS) + 2, column=0, columnspan=3, sticky="we")
        save_btn = ttk.Button(btns, text=t("settings.btn.save"), command=self._save)
        save_btn.pack(side="right", padx=4)
        cancel_btn = ttk.Button(btns, text=t("settings.btn.cancel"), command=self.root.destroy)
        cancel_btn.pack(side="right", padx=4)
        reload_btn = ttk.Button(btns, text=t("settings.btn.reload"), command=self._reload_from_disk)
        reload_btn.pack(side="left", padx=4)

    def _reload_from_disk(self) -> None:
        self.cfg = Config.load()
        for name, (kind, var) in self.widgets.items():
            current = getattr(self.cfg, name)
            if kind == "combo_lang":
                code_to_display = {
                    code: f"{emoji}  {name_}" for code, name_, emoji in LANGUAGES
                }
                var.set(code_to_display.get(str(current), str(current)))
            else:
                var.set(current)

    def _collect(self) -> Config:
        new = Config.load()
        # Walk widgets in insertion order; for combo_lang map display→code.
        row_widgets = list(self.root.winfo_children())[0].winfo_children()  # frm children
        for name, (kind, var) in self.widgets.items():
            if kind == "combo_lang":
                # Find the widget to consult its display→code map.
                mapping: dict[str, str] = {}
                for w in row_widgets:
                    if getattr(w, "_lang_display_to_code", None):
                        mapping = w._lang_display_to_code  # type: ignore[attr-defined]
                        break
                display_val = var.get()
                code = mapping.get(display_val, display_val)
                setattr(new, name, code)
            else:
                setattr(new, name, var.get())
        return new

    def _save(self) -> None:
        try:
            new = self._collect()
            new.validate()
            new.save()
        except Exception as e:
            messagebox.showerror(t("settings.title"), t("settings.error", err=e), parent=self.root)
            return

        # Apply language immediately in this process.
        set_language(new.language)
        # Tell the local monitor to use the new config.
        self.monitor.reload_config(new)
        # Tell the service to re-read config.toml (best effort).
        resp = pipe_call({"cmd": "reload_config"}, timeout_s=3.0)
        if not (resp and resp.get("ok")):
            log.warning("service reload_config failed: %s", resp)

        if self.on_saved:
            try:
                self.on_saved(new)
            except Exception:
                log.exception("on_saved callback failed")

        messagebox.showinfo(t("settings.title"), t("settings.saved"), parent=self.root)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


HELP_ENTRIES = [
    ("tray.status", "tray.status.desc"),
    ("tray.settings", "tray.settings.desc"),
    ("tray.probe", "tray.probe.desc"),
    ("tray.pause", "tray.pause.desc"),
    ("tray.enroll", "tray.enroll.desc"),
    ("tray.set_password", "tray.set_password.desc"),
    ("tray.open_log", "tray.open_log.desc"),
    ("tray.language", "tray.language.desc"),
    ("tray.help", "tray.help.desc"),
    ("tray.quit", "tray.quit.desc"),
]


class HelpWindow:
    """Lists every tray menu entry with its localised description."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(t("help.title"))
        self.root.geometry("620x560")
        self._build()

    def _build(self) -> None:
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=t("help.intro"), font=("", 10, "bold")).pack(anchor="w", pady=(0, 8))

        canvas = tk.Canvas(frm, highlightthickness=0)
        scroll = ttk.Scrollbar(frm, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)

        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))

        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for label_key, desc_key in HELP_ENTRIES:
            row = ttk.Frame(inner)
            row.pack(fill="x", pady=3, padx=2)
            ttk.Label(row, text=t(label_key), width=30, anchor="w",
                      font=("", 9, "bold")).pack(side="left")
            ttk.Label(row, text=t(desc_key), wraplength=380, justify="left",
                      foreground="#444").pack(side="left", fill="x", expand=True)

        btns = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        btns.pack(fill="x")
        ttk.Button(btns, text=t("help.close"), command=self.root.destroy).pack(side="right")

    def run(self) -> None:
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Launchers — isolate Tk into daemon threads so the tray stays responsive.
# Only one instance of each window at a time (simple lock-based singleton).
# ---------------------------------------------------------------------------
_window_locks: dict[str, threading.Lock] = {
    "status": threading.Lock(),
    "settings": threading.Lock(),
    "help": threading.Lock(),
}


def _launch_singleton(key: str, factory: Callable[[], object]) -> None:
    lock = _window_locks[key]
    if not lock.acquire(blocking=False):
        log.info("%s window already open; skipping duplicate", key)
        return

    def _run():
        try:
            obj = factory()
            obj.run()  # type: ignore[attr-defined]
        except Exception:
            log.exception("%s window crashed", key)
        finally:
            lock.release()

    threading.Thread(target=_run, name=f"{key}-window", daemon=True).start()


def open_status(monitor: PresenceMonitor) -> None:
    _launch_singleton("status", lambda: StatusWindow(monitor))


def open_settings(
    monitor: PresenceMonitor,
    on_saved: Callable[[Config], None] | None = None,
) -> None:
    _launch_singleton("settings", lambda: SettingsWindow(monitor, on_saved))


def open_help() -> None:
    _launch_singleton("help", lambda: HelpWindow())
