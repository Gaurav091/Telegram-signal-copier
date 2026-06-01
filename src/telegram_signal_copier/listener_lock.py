"""Backward-compatibility shim — listener lock helpers moved to listener.lock."""
from telegram_signal_copier.listener.lock import (  # noqa: F401
    _acquire_listener_lock as _acquire_listener_lock,
    _clear_listener_pid as _clear_listener_pid,
    _listener_lock_path as _listener_lock_path,
    _listener_pid_path as _listener_pid_path,
    _read_pid_value as _read_pid_value,
    _release_listener_lock as _release_listener_lock,
    _write_listener_pid as _write_listener_pid,
)
