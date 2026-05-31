"""Listener lock and PID file helpers.

Extracted from main.py for maintainability.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import suppress
from pathlib import Path

from telegram_signal_copier.config import AppConfig

logger = logging.getLogger(__name__)

_LISTENER_LOCK_HANDLE = None


def _listener_pid_path(config: AppConfig) -> Path:
    return config.project_root / "runtime" / "listener.pid"


def _listener_lock_path(config: AppConfig) -> Path:
    return config.project_root / "runtime" / "listener.lock"


def _read_pid_value(path: Path) -> int | None:
    try:
        raw_value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except Exception:
        logger.debug("_read_pid_value failed for %s", path, exc_info=True)
        return None
    return int(raw_value) if raw_value.isdigit() else None


def _acquire_listener_lock(config: AppConfig) -> bool:
    global _LISTENER_LOCK_HANDLE
    if _LISTENER_LOCK_HANDLE is not None:
        return True

    lock_path = _listener_lock_path(config)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if lock_path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                handle.close()
                return False
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                return False

        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n".encode("utf-8"))
        handle.flush()
        _LISTENER_LOCK_HANDLE = handle
        return True
    except Exception:
        handle.close()
        raise


def _release_listener_lock() -> None:
    global _LISTENER_LOCK_HANDLE

    handle = _LISTENER_LOCK_HANDLE
    _LISTENER_LOCK_HANDLE = None
    if handle is None:
        return

    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        logger.debug("_release_listener_lock: unlock failed", exc_info=True)
    finally:
        with suppress(Exception):
            handle.close()


def _write_listener_pid(config: AppConfig) -> None:
    from telegram_signal_copier.listener_status import _safe_write_text
    pid_path = _listener_pid_path(config)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    _safe_write_text(pid_path, f"{os.getpid()}\n")


def _clear_listener_pid(config: AppConfig) -> None:
    with suppress(FileNotFoundError):
        _listener_pid_path(config).unlink()
