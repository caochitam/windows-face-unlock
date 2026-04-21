"""Enrollment wizard — live camera preview, auto-capture, build embeddings.

Replaces the old ``python -m tools.enroll capture`` console flow. Runs in
the tray process so it can share i18n, widgets, and the FaceService pipe.

Flow
----
1. ``pause_camera`` on the FaceService so we own the webcam.
2. Open the camera in a background thread and publish BGR frames.
3. Render each frame with a green box around detected faces (YuNet).
4. When capture is armed and a face has been visible long enough, save
   the frame as JPG into ``ENROLL_DIR`` and increment the counter.
5. When the user hits "Build", call ``build_enrollment`` on the service
   which runs DeepFace and writes ``embeddings.npz``.
6. On close, always ``resume_camera`` so probes come back on.
"""
from __future__ import annotations
import logging
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Callable

import cv2
from PIL import Image, ImageTk

from face_service.config import ENROLL_DIR, EMBED_PATH
from face_service.detector import FaceDetector
from face_service.i18n import t

from .monitor import pipe_call
from .widgets import InfoButton, Tooltip, attach_tooltip

log = logging.getLogger(__name__)

PREVIEW_W = 480
PREVIEW_H = 360
CAPTURE_COOLDOWN_S = 1.0    # min gap between auto captures
FACE_STABLE_FRAMES = 3      # face must be seen this many frames before arming capture
DETECT_EVERY_N_FRAMES = 2   # YuNet is fast but skipping halves CPU
CAMERA_LEASE_S = 300        # ask service to hand over the camera for this long


def _count_enroll_images() -> int:
    try:
        return sum(
            1 for p in ENROLL_DIR.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
    except FileNotFoundError:
        return 0


def _has_embeddings() -> bool:
    return EMBED_PATH.exists()


class EnrollWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(t("enroll.title"))
        self.root.geometry(f"{PREVIEW_W + 60}x{PREVIEW_H + 320}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.detector = FaceDetector()
        self._stop = threading.Event()
        self._capture_armed = threading.Event()
        self._cam_thread: threading.Thread | None = None
        self._latest_tk_image: ImageTk.PhotoImage | None = None
        self._face_streak = 0
        self._last_capture_ts = 0.0
        self._captured = 0
        self._target = 15
        self._building = False

        self._lease_ok = self._acquire_camera_lease()

        self._build_ui()
        self._refresh_existing_stats()
        self._set_guide("enroll.guide.idle")

        # Start the preview immediately so the user sees themselves.
        self._cam_thread = threading.Thread(
            target=self._camera_loop, name="enroll-camera", daemon=True
        )
        self._cam_thread.start()

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        # Camera preview canvas
        self.preview = tk.Label(frm, background="#222",
                                width=PREVIEW_W, height=PREVIEW_H)
        self.preview.pack(pady=(0, 8))

        # Big guidance line
        self.guide_var = tk.StringVar(value="")
        guide = ttk.Label(frm, textvariable=self.guide_var,
                          wraplength=PREVIEW_W, justify="center",
                          font=("", 10, "bold"))
        guide.pack(fill="x", pady=(0, 6))

        # Progress row
        prog_row = ttk.Frame(frm)
        prog_row.pack(fill="x", pady=(0, 6))
        self.progress = ttk.Progressbar(prog_row, mode="determinate",
                                        maximum=self._target)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.progress_var = tk.StringVar(value="0/15")
        ttk.Label(prog_row, textvariable=self.progress_var,
                  width=8, anchor="e").pack(side="right")

        # Count spinbox
        count_row = ttk.Frame(frm)
        count_row.pack(fill="x", pady=4)
        ttk.Label(count_row, text=t("enroll.count") + ":",
                  width=22, anchor="w").pack(side="left")
        self.count_var = tk.IntVar(value=self._target)
        self.count_spin = ttk.Spinbox(
            count_row, from_=5, to=40, textvariable=self.count_var,
            width=6, command=self._on_count_changed,
        )
        self.count_spin.pack(side="left")
        attach_tooltip(self.count_spin, "enroll.count")

        # Existing data label
        self.existing_var = tk.StringVar()
        ttk.Label(frm, textvariable=self.existing_var,
                  foreground="#555").pack(anchor="w", pady=(2, 6))

        # Buttons row
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(4, 0))
        self.start_btn = ttk.Button(btns, text=t("enroll.btn.start"),
                                    command=self._on_start_stop)
        self.start_btn.pack(side="left", padx=3)
        self.build_btn = ttk.Button(btns, text=t("enroll.btn.build"),
                                    command=self._on_build)
        self.build_btn.pack(side="left", padx=3)
        self.wipe_btn = ttk.Button(btns, text=t("enroll.btn.wipe"),
                                   command=self._on_wipe)
        self.wipe_btn.pack(side="left", padx=3)
        ttk.Button(btns, text=t("enroll.btn.close"),
                   command=self._on_close).pack(side="right", padx=3)

        # Render a first black frame so the layout doesn't collapse.
        blank = Image.new("RGB", (PREVIEW_W, PREVIEW_H), (24, 24, 24))
        self._latest_tk_image = ImageTk.PhotoImage(blank)
        self.preview.configure(image=self._latest_tk_image)

    # ---------------- helpers ----------------

    def _set_guide(self, key: str, **kwargs) -> None:
        self.guide_var.set(t(key, **kwargs))

    def _refresh_existing_stats(self) -> None:
        n = _count_enroll_images()
        has = t("enroll.has.yes") if _has_embeddings() else t("enroll.has.no")
        self.existing_var.set(t("enroll.existing", n=n, has=has))

    def _on_count_changed(self) -> None:
        try:
            v = int(self.count_var.get())
        except (ValueError, tk.TclError):
            return
        self._target = max(1, v)
        self.progress.configure(maximum=self._target)
        self.progress_var.set(f"{self._captured}/{self._target}")

    def _update_progress(self) -> None:
        self.progress["value"] = self._captured
        self.progress_var.set(f"{self._captured}/{self._target}")

    def _acquire_camera_lease(self) -> bool:
        resp = pipe_call(
            {"cmd": "pause_camera", "seconds": CAMERA_LEASE_S},
            timeout_s=3.0,
        )
        if not (resp and resp.get("ok")):
            log.warning("could not pause face_service camera: %s", resp)
            messagebox.showwarning(
                t("enroll.title"),
                t("enroll.error.service_busy"),
                parent=self.root,
            )
            return False
        return True

    def _release_camera_lease(self) -> None:
        pipe_call({"cmd": "resume_camera"}, timeout_s=3.0)

    # ---------------- camera thread ----------------

    def _camera_loop(self) -> None:
        cap = None
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            candidate = cv2.VideoCapture(0, backend)
            if candidate.isOpened():
                candidate.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                candidate.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap = candidate
                break
            candidate.release()

        if cap is None:
            self.root.after(0, lambda: messagebox.showerror(
                t("enroll.title"), t("enroll.error.camera"),
                parent=self.root,
            ))
            return

        try:
            frame_idx = 0
            faces: list[tuple[int, int, int, int]] = []
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.05)
                    continue
                frame_idx += 1

                # Detect every few frames to save CPU but still feel live.
                if frame_idx % DETECT_EVERY_N_FRAMES == 0:
                    faces = self._detect_faces(frame)

                self._process_capture(frame, bool(faces))

                annotated = self._annotate(frame, faces)
                self._post_preview(annotated)
                time.sleep(0.03)  # ~30 fps cap
        finally:
            cap.release()

    def _detect_faces(self, bgr) -> list[tuple[int, int, int, int]]:
        try:
            h, w = bgr.shape[:2]
            det = self.detector._ensure(w, h)  # type: ignore[attr-defined]
            _, res = det.detect(bgr)
            if res is None:
                return []
            boxes = []
            for row in res:
                x, y, ww, hh = int(row[0]), int(row[1]), int(row[2]), int(row[3])
                boxes.append((x, y, ww, hh))
            return boxes
        except Exception as e:
            log.debug("detect failed: %s", e)
            return []

    def _annotate(self, bgr, faces):
        import numpy as np
        img = bgr.copy()
        for (x, y, w, h) in faces:
            cv2.rectangle(img, (x, y), (x + w, y + h), (30, 220, 30), 3)
        # Flip horizontally so the preview feels like a mirror.
        img = cv2.flip(img, 1)
        # Resize to the preview dims, keep aspect.
        h0, w0 = img.shape[:2]
        scale = min(PREVIEW_W / w0, PREVIEW_H / h0)
        new_w, new_h = int(w0 * scale), int(h0 * scale)
        img = cv2.resize(img, (new_w, new_h))
        # Center-pad to (PREVIEW_W, PREVIEW_H)
        canvas = np.zeros((PREVIEW_H, PREVIEW_W, 3), dtype=img.dtype)
        ox = (PREVIEW_W - new_w) // 2
        oy = (PREVIEW_H - new_h) // 2
        canvas[oy:oy + new_h, ox:ox + new_w] = img
        return cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)

    def _post_preview(self, rgb) -> None:
        try:
            pil = Image.fromarray(rgb)
            img = ImageTk.PhotoImage(pil)
        except Exception:
            return

        def apply():
            # Hold the reference; ImageTk requires it.
            self._latest_tk_image = img
            try:
                self.preview.configure(image=img)
            except tk.TclError:
                pass

        try:
            self.root.after(0, apply)
        except RuntimeError:
            pass

    def _process_capture(self, frame, face_present: bool) -> None:
        if self._building:
            return

        if face_present:
            self._face_streak += 1
        else:
            self._face_streak = 0

        if not self._capture_armed.is_set():
            # Passive preview: just update the guide if it changed.
            if face_present and self._face_streak >= FACE_STABLE_FRAMES:
                self._queue_guide("enroll.guide.idle")
            elif not face_present:
                self._queue_guide("enroll.guide.no_face")
            return

        # Armed: capture when face is stable and cooldown elapsed.
        now = time.time()
        if not face_present or self._face_streak < FACE_STABLE_FRAMES:
            self._queue_guide("enroll.guide.no_face")
            return
        if now - self._last_capture_ts < CAPTURE_COOLDOWN_S:
            return
        if self._captured >= self._target:
            self._capture_armed.clear()
            self._queue_guide("enroll.guide.done_capture", n=self._target)
            self._queue_refresh_buttons()
            return

        try:
            ENROLL_DIR.mkdir(parents=True, exist_ok=True)
            path = ENROLL_DIR / f"enroll_{int(now * 1000)}.jpg"
            cv2.imwrite(str(path), frame)
            self._captured += 1
            self._last_capture_ts = now
            log.info("enroll: saved %s (%d/%d)", path.name, self._captured, self._target)
        except Exception:
            log.exception("failed to save enroll frame")
            return

        self._queue_update_progress()
        self._queue_guide("enroll.guide.capturing",
                          i=self._captured, n=self._target)

    def _queue_guide(self, key: str, **kwargs) -> None:
        try:
            self.root.after(0, lambda: self._set_guide(key, **kwargs))
        except RuntimeError:
            pass

    def _queue_update_progress(self) -> None:
        try:
            self.root.after(0, self._update_progress)
        except RuntimeError:
            pass

    def _queue_refresh_buttons(self) -> None:
        try:
            self.root.after(0, lambda: self.start_btn.configure(text=t("enroll.btn.start")))
        except RuntimeError:
            pass

    # ---------------- button actions ----------------

    def _on_start_stop(self) -> None:
        if self._capture_armed.is_set():
            self._capture_armed.clear()
            self.start_btn.configure(text=t("enroll.btn.start"))
            self._set_guide("enroll.guide.idle")
            return

        # (re)start a session: reset counters
        self._captured = 0
        self._last_capture_ts = 0.0
        try:
            self._target = max(1, int(self.count_var.get()))
        except Exception:
            self._target = 15
        self.progress.configure(maximum=self._target)
        self._update_progress()
        self._capture_armed.set()
        self.start_btn.configure(text=t("enroll.btn.stop"))
        self._set_guide("enroll.guide.capturing", i=0, n=self._target)

    def _on_build(self) -> None:
        if self._building:
            return
        if _count_enroll_images() == 0:
            messagebox.showwarning(
                t("enroll.title"),
                t("enroll.guide.build_empty"),
                parent=self.root,
            )
            return

        self._building = True
        self._capture_armed.clear()
        self.start_btn.configure(state="disabled")
        self.build_btn.configure(state="disabled")
        self.wipe_btn.configure(state="disabled")
        self._set_guide("enroll.guide.building")

        def worker():
            # Call the service — it already has DeepFace loaded and warm.
            resp = pipe_call({"cmd": "build_enrollment"}, timeout_s=120.0)
            def done():
                self._building = False
                self.start_btn.configure(state="normal")
                self.build_btn.configure(state="normal")
                self.wipe_btn.configure(state="normal")
                self._refresh_existing_stats()
                if resp and resp.get("ok"):
                    n = int(resp.get("count", 0))
                    if n > 0:
                        self._set_guide("enroll.guide.done", n=n)
                    else:
                        self._set_guide("enroll.guide.build_empty")
                else:
                    reason = (resp or {}).get("reason") or "?"
                    self._set_guide("enroll.guide.build_empty")
                    messagebox.showerror(
                        t("enroll.title"),
                        f"build_enrollment: {reason}",
                        parent=self.root,
                    )
            try:
                self.root.after(0, done)
            except RuntimeError:
                pass

        threading.Thread(target=worker, name="enroll-build", daemon=True).start()

    def _on_wipe(self) -> None:
        if not messagebox.askyesno(
            t("enroll.confirm.wipe.title"),
            t("enroll.confirm.wipe.body"),
            parent=self.root,
        ):
            return

        try:
            if ENROLL_DIR.exists():
                for p in ENROLL_DIR.iterdir():
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                        try:
                            p.unlink()
                        except Exception:
                            log.exception("delete %s", p)
            if EMBED_PATH.exists():
                EMBED_PATH.unlink()
        except Exception:
            log.exception("wipe failed")

        self._captured = 0
        self._update_progress()
        self._refresh_existing_stats()
        self._set_guide("enroll.guide.idle")

    def _on_close(self) -> None:
        # Signal the camera thread first and WAIT for it to release the
        # webcam before we tear down Tk. Skipping the join would let the
        # daemon thread get cut mid-read(), which on Windows DirectShow
        # leaks the camera handle and wedges the whole service until a
        # full process restart (we hit this in production 2026-04-21).
        self._stop.set()
        self._capture_armed.clear()
        t_cam = self._cam_thread
        if t_cam is not None and t_cam.is_alive():
            # cv2.VideoCapture.read() blocks up to ~30 ms per frame, so
            # a 3 s budget is generous but still bounded.
            t_cam.join(timeout=3.0)
            if t_cam.is_alive():
                log.warning("enroll camera thread did not exit within 3s")
        try:
            self.root.destroy()
        except Exception:
            pass
        self._release_camera_lease()

    def run(self) -> None:
        self.root.mainloop()


# Singleton launcher — one wizard at a time.
_enroll_lock = threading.Lock()


def open_enroll() -> None:
    if not _enroll_lock.acquire(blocking=False):
        log.info("enroll window already open; skipping duplicate")
        return

    def _run():
        try:
            EnrollWindow().run()
        except Exception:
            log.exception("enroll window crashed")
        finally:
            _enroll_lock.release()

    threading.Thread(target=_run, name="enroll-window", daemon=True).start()
