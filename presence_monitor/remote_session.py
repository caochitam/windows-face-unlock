"""Detect remote-access contexts so the presence monitor can skip auto-lock.

Two tiers of detection:

1. ALWAYS_REMOTE_PROCS — processes that only exist while a remote session is
   *currently connected* (e.g. TeamViewer_Desktop.exe, Quick Assist).
   Seeing them is enough to treat as remote.

2. CONNECTION_CHECKED_PROCS — processes that run persistently (tray / service)
   and only mean "active remote" when they hold an ESTABLISHED TCP connection
   to a non-loopback peer (UltraViewer, AnyDesk, RustDesk, Parsec, ...).

Also: RDP session via GetSystemMetrics(SM_REMOTESESSION).
"""
from __future__ import annotations
import ipaddress
import logging

try:
    import psutil  # optional but recommended
except ImportError:
    psutil = None  # type: ignore

import win32api  # type: ignore

log = logging.getLogger(__name__)

# Always indicate an active remote connection on sight.
ALWAYS_REMOTE_PROCS = {
    "teamviewer_desktop.exe",      # TeamViewer spawns this on connect
    "remoting_desktop.exe",        # Chrome Remote Desktop (per-connection)
    "quickassist.exe",             # Microsoft Quick Assist
    "msra.exe",                    # Windows Remote Assistance
}

# Tray/service processes that run all the time; only treat as active when
# they hold an ESTABLISHED external TCP connection.
CONNECTION_CHECKED_PROCS = {
    "ultraviewer_desktop.exe",
    "ultraviewer_service.exe",
    "anydesk.exe",
    "rustdesk.exe",
    "remoting_host.exe",           # Chrome Remote Desktop host
    "parsecd.exe",
    "sunshine.exe",
    "srserver.exe",                # Splashtop
    "teamviewer.exe",              # full idle tray (checked via connection)
}

SM_REMOTESESSION = 0x1000


def _is_external(addr: str) -> bool:
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (ip.is_loopback or ip.is_unspecified or ip.is_link_local)


def is_rdp_session() -> bool:
    try:
        return bool(win32api.GetSystemMetrics(SM_REMOTESESSION))
    except Exception as e:
        log.debug("GetSystemMetrics failed: %s", e)
        return False


def _proc_has_external_established(proc: "psutil.Process") -> bool:
    try:
        for c in proc.net_connections(kind="tcp"):
            if c.status == psutil.CONN_ESTABLISHED and c.raddr and _is_external(c.raddr.ip):
                return True
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False
    except Exception as e:
        log.debug("net_connections failed: %s", e)
    return False


def active_remote_tools() -> list[str]:
    if psutil is None:
        return []
    found: list[str] = []
    for p in psutil.process_iter(attrs=["name"]):
        try:
            name = (p.info.get("name") or "").lower()
        except Exception:
            continue
        if name in ALWAYS_REMOTE_PROCS:
            found.append(name)
        elif name in CONNECTION_CHECKED_PROCS:
            if _proc_has_external_established(p):
                found.append(f"{name}(connected)")
    return found


def is_remote_context() -> tuple[bool, str]:
    if is_rdp_session():
        return True, "rdp"
    tools = active_remote_tools()
    if tools:
        return True, "remote-tool:" + ",".join(sorted(set(tools)))
    return False, ""
