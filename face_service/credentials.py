"""Store the user's Windows password encrypted via DPAPI (user scope).

DPAPI-encrypted blobs can only be decrypted by the SAME Windows user on the
SAME machine. They are safe from other users but *not* from malware running
as that same user. For a higher security bar you would use a TPM-backed
Credential Manager entry.
"""
from __future__ import annotations
import json
from pathlib import Path

import win32crypt  # type: ignore

from .config import CREDS_PATH


ENTROPY = b"face-unlock:v1"


def save_password(username: str, password: str, domain: str = ".") -> None:
    blob = json.dumps({"u": username, "p": password, "d": domain}).encode("utf-8")
    enc = win32crypt.CryptProtectData(blob, "face-unlock", ENTROPY, None, None, 0)
    CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDS_PATH.write_bytes(enc)


def load_password() -> dict | None:
    if not CREDS_PATH.exists():
        return None
    enc = CREDS_PATH.read_bytes()
    _, data = win32crypt.CryptUnprotectData(enc, ENTROPY, None, None, 0)
    return json.loads(data.decode("utf-8"))


def clear_password() -> None:
    if CREDS_PATH.exists():
        CREDS_PATH.unlink()
