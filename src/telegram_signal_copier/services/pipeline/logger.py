"""Structured JSONL pipeline logging (AGENT_SPEC section 13).

Every analysis decision — from intent classification through execution —
is logged as a single JSON object on one line in::

    logs/pipeline_YYYYMMDD.jsonl

This format can be queried with ``jq``, loaded into pandas, or tailed in
real time.  Log rotation is date-based (one file per UTC day).

Usage
-----
    from telegram_signal_copier.services.pipeline_logger import PipelineLogger

    pipeline_log = PipelineLogger(logs_dir=config.project_root / "logs")

    pipeline_log.log(
        group_id="abc123",
        channel_id=1234567890,
        message_count=2,
        image_count=1,
        intent="NEW_SIGNAL",
        intent_confidence=0.97,
        extraction=signal,        # ExtractedSignal | None
        validation=validated,     # ValidatedSignal | None
        rejection_reasons=[],
        action_taken="OPEN_TRADE",
        execution_status="DRY_RUN",
        order_ticket="DRY_RUN",
    )
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PipelineLogger:
    """Thread-safe JSONL pipeline event logger with daily file rotation."""

    def __init__(self, logs_dir: str | Path) -> None:
        self._logs_dir = Path(logs_dir)
        self._lock = threading.Lock()
        self._current_date: str = ""
        self._handle = None

    # ── Public API ────────────────────────────────────────────────────────

    def log(
        self,
        group_id: str,
        channel_id: int,
        message_count: int,
        image_count: int,
        intent: Optional[str],
        intent_confidence: float,
        intent_reasoning: str = "",
        extraction: Any = None,   # ExtractedSignal | dict | None
        validation: Any = None,   # ValidatedSignal | dict | None
        rejection_reasons: list[str] | None = None,
        action_taken: str = "IGNORE",
        execution_status: str | None = None,
        order_ticket: str | None = None,
        execution_error: str | None = None,
        source_group: str = "",
        message_id: str = "",
        raw_text_snippet: str = "",
    ) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "group_id": group_id,
            "channel_id": channel_id,
            "source_group": source_group,
            "message_id": message_id,
            "message_count": message_count,
            "image_count": image_count,
            "text_snippet": raw_text_snippet[:200] if raw_text_snippet else "",
            "intent": intent,
            "intent_confidence": round(intent_confidence, 4),
            "intent_reasoning": intent_reasoning,
            "extraction": _serialize(extraction),
            "validation": _serialize(validation),
            "rejection_reasons": rejection_reasons or [],
            "action_taken": action_taken,
            "execution_status": execution_status,
            "order_ticket": order_ticket,
            "execution_error": execution_error,
        }
        self._write(entry)

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                try:
                    self._handle.close()
                except Exception:
                    pass
                self._handle = None

    # ── Internal ──────────────────────────────────────────────────────────

    def _write(self, entry: dict) -> None:
        line = json.dumps(entry, default=str)
        with self._lock:
            try:
                handle = self._get_handle()
                handle.write(line + "\n")
                handle.flush()
            except Exception:
                logger.exception("[PIPELINE_LOG] Failed to write log entry")

    def _get_handle(self):
        """Return an open file handle, rotating if the UTC date changed."""
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        if today != self._current_date or self._handle is None:
            if self._handle is not None:
                try:
                    self._handle.close()
                except Exception:
                    pass
            try:
                self._logs_dir.mkdir(parents=True, exist_ok=True)
                path = self._logs_dir / f"pipeline_{today}.jsonl"
                self._handle = open(path, "a", encoding="utf-8")  # noqa: SIM115,WPS515
                self._current_date = today
            except Exception:
                logger.exception("[PIPELINE_LOG] Could not open log file for %s", today)
                raise
        return self._handle


def _serialize(obj: Any) -> Any:
    """Convert Pydantic models or dataclasses to plain dicts for JSON."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    # Pydantic v2
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    # Pydantic v1 / dataclasses
    if hasattr(obj, "dict"):
        return obj.dict(exclude_none=True)
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)
    return str(obj)
