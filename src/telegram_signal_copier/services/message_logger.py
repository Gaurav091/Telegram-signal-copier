"""Raw Telegram message logger.

Writes every message received from a configured Telegram source to a
daily JSONL file at::

    logs/telegram_messages_YYYYMMDD.jsonl

This gives the smart supervisor a ground truth of *all* messages that
arrived at the listener — enabling cross-referencing against the pipeline
log to detect trades that were missed, incorrectly rejected, or silently
dropped.

Each entry:
    {
        "ts":            "2026-05-19T18:30:00+00:00",   ISO-8601 UTC
        "source_group":  "GOLD VIP SIGNALS",
        "message_id":    "12345",
        "chat_id":       "1935701558",
        "text":          "BUY XAUUSD ...",              first 1000 chars
        "has_image":     false
    }
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_INSTANCE: "RawMessageLogger | None" = None
_LOCK = threading.Lock()


class RawMessageLogger:
    """Thread-safe daily-rotating JSONL logger for raw Telegram messages."""

    def __init__(self, logs_dir: str | Path) -> None:
        self._logs_dir = Path(logs_dir)
        self._lock = threading.Lock()
        self._current_date: str = ""
        self._handle = None

    def log(
        self,
        source_group: str,
        message_id: str,
        chat_id: str,
        raw_text: str,
        has_image: bool = False,
    ) -> None:
        entry = {
            "ts":           datetime.now(tz=UTC).isoformat(),
            "source_group": source_group,
            "message_id":   message_id,
            "chat_id":      chat_id,
            "text":         raw_text[:1000],
            "has_image":    has_image,
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            try:
                fh = self._get_handle()
                fh.write(line + "\n")
                fh.flush()
            except Exception:
                logger.exception("[MSG_LOG] Failed to write raw message log")

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                try:
                    self._handle.close()
                except Exception:
                    pass
                self._handle = None

    def _get_handle(self):
        today = datetime.now(tz=UTC).strftime("%Y%m%d")
        if today != self._current_date or self._handle is None:
            if self._handle is not None:
                try:
                    self._handle.close()
                except Exception:
                    pass
            self._logs_dir.mkdir(parents=True, exist_ok=True)
            path = self._logs_dir / f"telegram_messages_{today}.jsonl"
            self._handle = open(path, "a", encoding="utf-8")  # noqa: SIM115
            self._current_date = today
        return self._handle


def init(logs_dir: str | Path) -> RawMessageLogger:
    """Initialise the module-level singleton and return it."""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = RawMessageLogger(logs_dir)
    return _INSTANCE


def get() -> "RawMessageLogger | None":
    """Return the singleton (None if not yet initialised)."""
    return _INSTANCE
