"""Capture enrollment images from the webcam, or import from a folder.

Usage:
  python -m tools.enroll capture           # take 10 photos, 1s apart
  python -m tools.enroll capture --count 20
  python -m tools.enroll from-dir PATH     # copy/link images from PATH
  python -m tools.enroll build             # compute embeddings from enroll dir
"""
from __future__ import annotations
import argparse
import shutil
import time
from pathlib import Path

import cv2

from face_service.camera import Camera
from face_service.config import Config, ENROLL_DIR
from face_service.recognizer import Recognizer


def cmd_capture(count: int) -> None:
    ENROLL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Capturing {count} images into {ENROLL_DIR}")
    print("Move your head slightly between frames (different angles help).")
    with Camera(0) as cam:
        for i in range(count):
            for _ in range(5):
                cam.read()
            frame = cam.read()
            if frame is None:
                print(f"  [{i+1}/{count}] no frame, retry")
                time.sleep(0.5)
                continue
            p = ENROLL_DIR / f"enroll_{int(time.time()*1000)}.jpg"
            cv2.imwrite(str(p), frame)
            print(f"  [{i+1}/{count}] saved {p.name}")
            time.sleep(1.0)


def cmd_from_dir(src: Path) -> None:
    ENROLL_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in Path(src).iterdir():
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            shutil.copy2(p, ENROLL_DIR / p.name)
            n += 1
    print(f"Copied {n} images into {ENROLL_DIR}")


def cmd_build() -> None:
    cfg = Config.load()
    n = Recognizer(cfg).enroll_from_dir(ENROLL_DIR)
    print(f"Built embeddings from {n} images.")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture"); c.add_argument("--count", type=int, default=10)
    d = sub.add_parser("from-dir"); d.add_argument("path")
    sub.add_parser("build")
    args = ap.parse_args()

    if args.cmd == "capture":
        cmd_capture(args.count)
        cmd_build()
    elif args.cmd == "from-dir":
        cmd_from_dir(Path(args.path))
        cmd_build()
    elif args.cmd == "build":
        cmd_build()


if __name__ == "__main__":
    main()
