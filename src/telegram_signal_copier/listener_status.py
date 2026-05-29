"""Listener status file and bridge status write helpers.

Extracted from main.py for maintainability.
"""
from __future__ import annotations

import logging
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from telegram_signal_copier.config import AppConfig

logger = logging.getLogger(__name__)


def _status_file_content(status: dict[str, object]) -> str:
    lines: list[str] = []
    for key, value in status.items():
        if value is None:
            normalized = ""
        elif isinstance(value, list):
            normalized = "|".join(str(item) for item in value)
        else:
            normalized = str(value)
        normalized = " ".join(normalized.splitlines())
        lines.append(f"{key}={normalized}")
    return "\n".join(lines) + "\n"


def _safe_write_text(path: Path, content: str, attempts: int = 5, delay_seconds: float = 0.1) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    for attempt in range(attempts):
        try:
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(path)
            return
        except PermissionError:
            try:
                path.write_text(content, encoding="utf-8")
                with suppress(FileNotFoundError):
                    temp_path.unlink()
                return
            except PermissionError:
                pass
            with suppress(FileNotFoundError):
                temp_path.unlink()
            if attempt == attempts - 1:
                return
            time.sleep(delay_seconds)


def _bridge_root_path(config: AppConfig) -> Path:
    bridge_root = config.bridge_inbox_dir
    try:
        if bridge_root.name.lower() == "inbox":
            return bridge_root.parent
    except Exception:
        logger.debug("_bridge_root_path: unexpected path error", exc_info=True)
    return bridge_root


def _write_bridge_status(config: AppConfig, status: dict[str, object]) -> None:
    now = datetime.now(tz=UTC)
    payload = {
        "listener_state": status.get("listener_state", "unknown"),
        "telegram_connected": status.get("telegram_connected", "0"),
        "session_name": status.get("session_name", config.telegram_session_name),
        "identity": status.get("identity", config.telegram_username or ""),
        "source_count": status.get("source_count", len(config.telegram_source_mappings)),
        "heartbeat_epoch": int(now.timestamp()),
        "heartbeat_display": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_source_group": status.get("last_source_group", ""),
        "last_message_id": status.get("last_message_id", ""),
        "last_decision": status.get("last_decision", ""),
        "last_execution_status": status.get("last_execution_status", ""),
        "last_symbol": status.get("last_symbol", ""),
        "last_side": status.get("last_side", ""),
        "last_order_type": status.get("last_order_type", ""),
        "last_entry_price": status.get("last_entry_price", ""),
        "last_stop_loss": status.get("last_stop_loss", ""),
        "last_take_profits": status.get("last_take_profits", []),
        "last_confidence": status.get("last_confidence", ""),
        "last_trade_comment": status.get("last_trade_comment", ""),
        "last_error": status.get("last_error", ""),
    }
    status_path = _bridge_root_path(config) / "telegram_status.txt"
    _safe_write_text(status_path, _status_file_content(payload))


def _write_source_map(config: AppConfig) -> None:
    lines = [
        f"{index}. {label} -> {identifier}"
        for index, (label, identifier) in enumerate(config.telegram_source_mappings, start=1)
    ]
    if not lines:
        lines = ["No Telegram sources configured"]
    source_map_path = _bridge_root_path(config) / "telegram_sources.txt"
    _safe_write_text(source_map_path, "\n".join(lines) + "\n")
