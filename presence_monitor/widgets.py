"""Shared tkinter widgets — Tooltip + InfoButton.

These are intentionally tiny: tkinter has no built-in hover tooltip, and
building one as a ``Toplevel`` with ``<Enter>``/``<Leave>`` bindings is
standard practice. The ``InfoButton`` is a small clickable label whose
tooltip is the localised description for a given i18n key.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Callable

from face_service.i18n import t

INFO_GLYPH = "ⓘ"


class Tooltip:
    """Hover tooltip for any tk widget.

    Uses a borderless Toplevel positioned near the cursor. Safe to create
    many of these; they share no state.
    """

    def __init__(
        self,
        widget: tk.Widget,
        text_provider: Callable[[], str],
        delay_ms: int = 450,
        wraplength: int = 360,
    ):
        self.widget = widget
        self.text_provider = text_provider
        self.delay_ms = delay_ms
        self.wraplength = wraplength
        self._after_id: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _e):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _on_leave(self, _e):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        try:
            text = self.text_provider()
        except Exception:
            return
        if not text:
            return
        # Position slightly below-right of the widget.
        try:
            x = self.widget.winfo_rootx() + 16
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except tk.TclError:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tip.attributes("-topmost", True)
        lbl = tk.Label(
            tip,
            text=text,
            justify="left",
            background="#ffffe0",
            foreground="#222",
            relief="solid",
            borderwidth=1,
            wraplength=self.wraplength,
            padx=6,
            pady=3,
        )
        lbl.pack()
        self._tip = tip

    def _hide(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class InfoButton(ttk.Label):
    """Small clickable (ⓘ) label. Hover shows tooltip; click shows messagebox."""

    def __init__(self, master: tk.Widget, i18n_key: str, **kwargs):
        super().__init__(master, text=INFO_GLYPH, cursor="question_arrow", **kwargs)
        self.i18n_key = i18n_key
        self.configure(foreground="#2a6dbf")
        self.bind("<Button-1>", self._on_click)
        Tooltip(self, lambda: t(self.i18n_key))

    def _on_click(self, _e):
        from tkinter import messagebox
        messagebox.showinfo(t("settings.info.title"), t(self.i18n_key), parent=self.winfo_toplevel())


def attach_tooltip(widget: tk.Widget, i18n_key: str) -> Tooltip:
    """Convenience: attach a tooltip whose text is ``t(i18n_key)``."""
    return Tooltip(widget, lambda: t(i18n_key))
