"""Backward-compatibility shim — listener status helpers moved to listener.status."""
from telegram_signal_copier.listener.status import (  # noqa: F401
    _bridge_root_path as _bridge_root_path,
    _safe_write_text as _safe_write_text,
    _write_bridge_status as _write_bridge_status,
    _write_source_map as _write_source_map,
)
