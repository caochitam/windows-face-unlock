from __future__ import annotations
import logging
from pathlib import Path
import numpy as np

from .config import Config, EMBED_PATH, ENROLL_DIR

log = logging.getLogger(__name__)


def _lazy_deepface():
    # Imported lazily because TensorFlow import is slow and heavy.
    from deepface import DeepFace  # type: ignore
    return DeepFace


class Recognizer:
    """Face recognizer backed by DeepFace. Stores a set of reference embeddings."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._refs: np.ndarray | None = None  # shape (N, D)

    # ---------- enrollment ----------

    def enroll_from_dir(self, directory: Path = ENROLL_DIR) -> int:
        DeepFace = _lazy_deepface()
        directory.mkdir(parents=True, exist_ok=True)
        images = [p for p in directory.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
        if not images:
            raise RuntimeError(f"No enroll images in {directory}")

        vecs: list[np.ndarray] = []
        for p in images:
            try:
                reps = DeepFace.represent(
                    img_path=str(p),
                    model_name=self.cfg.model_name,
                    detector_backend=self.cfg.detector_backend,
                    enforce_detection=True,
                    align=True,
                )
                if reps:
                    vecs.append(np.asarray(reps[0]["embedding"], dtype=np.float32))
                    log.info("enrolled %s", p.name)
            except Exception as e:
                log.warning("skip %s: %s", p.name, e)

        if not vecs:
            raise RuntimeError("No face found in enroll images")
        embeds = np.stack(vecs, axis=0)
        EMBED_PATH.parent.mkdir(parents=True, exist_ok=True)
        np.savez(EMBED_PATH, embeddings=embeds)
        self._refs = embeds
        return len(vecs)

    def load(self) -> bool:
        if not EMBED_PATH.exists():
            return False
        data = np.load(EMBED_PATH)
        self._refs = data["embeddings"]
        return True

    # ---------- verification ----------

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        na = a / (np.linalg.norm(a) + 1e-9)
        nb = b / (np.linalg.norm(b) + 1e-9)
        return float(1.0 - np.dot(na, nb))  # cosine *distance*

    def verify_frame(self, bgr: np.ndarray) -> tuple[bool, float, bool]:
        """Return (is_match, best_distance, is_real). `is_real` False if anti-spoofing flagged."""
        DeepFace = _lazy_deepface()
        if self._refs is None and not self.load():
            raise RuntimeError("No enrollment found. Run enroll first.")

        # Liveness via DeepFace.extract_faces(anti_spoofing=True)
        is_real = True
        if self.cfg.anti_spoofing:
            try:
                faces = DeepFace.extract_faces(
                    img_path=bgr,
                    detector_backend=self.cfg.detector_backend,
                    anti_spoofing=True,
                    enforce_detection=True,
                )
                if not faces:
                    return False, 1.0, False
                is_real = bool(faces[0].get("is_real", True))
                if not is_real:
                    return False, 1.0, False
            except Exception as e:
                log.warning("liveness check failed: %s", e)
                return False, 1.0, False

        try:
            reps = DeepFace.represent(
                img_path=bgr,
                model_name=self.cfg.model_name,
                detector_backend=self.cfg.detector_backend,
                enforce_detection=True,
                align=True,
            )
        except Exception as e:
            log.debug("no face: %s", e)
            return False, 1.0, is_real

        if not reps:
            return False, 1.0, is_real

        emb = np.asarray(reps[0]["embedding"], dtype=np.float32)
        dists = [self._cosine(emb, r) for r in self._refs]  # type: ignore[arg-type]
        best = min(dists)
        return best <= self.cfg.threshold, best, is_real
