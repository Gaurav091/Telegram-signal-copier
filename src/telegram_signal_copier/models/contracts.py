from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import re
from typing import Iterable
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def _iso_to_epoch_text(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(int(datetime.fromisoformat(value).timestamp()))
    except ValueError:
        return ""


def _comment_source_slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").upper()
    return cleaned or "UNKNOWN"


@dataclass(slots=True)
class TelegramSignalMessage:
    source_group: str
    message_id: str
    raw_text: str = ""
    image_path: str | None = None
    sender: str | None = None
    received_at: str = field(default_factory=_now_iso)
    # All image paths when multiple images are grouped from one source window
    all_image_paths: list[str] = field(default_factory=list)
    # Grouped message count (>1 means buffer flushed multiple messages)
    grouped_count: int = 1

    def combined_text(self) -> str:
        return _normalize_text(self.raw_text)

    def effective_image_paths(self) -> list[str]:
        """Return deduplicated list of all available images, primary first."""
        paths: list[str] = []
        if self.image_path and self.image_path not in paths:
            paths.append(self.image_path)
        for p in self.all_image_paths:
            if p and p not in paths:
                paths.append(p)
        return paths


@dataclass(slots=True)
class ParsedSignal:
    source_group: str
    message_id: str
    symbol: str | None
    side: str | None
    order_type: str = "MARKET"
    entry_price: float | None = None
    entry_range_low: float | None = None
    entry_range_high: float | None = None
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    confidence: float = 0.0
    raw_text: str = ""
    image_used: bool = False
    requires_review: bool = False
    parser_name: str = "heuristic"
    notes: list[str] = field(default_factory=list)

    def signature(self) -> str:
        digest_source = "|".join(
            [
                self.source_group,
                self.message_id,
                self.symbol or "",
                self.side or "",
                self.order_type,
                str(self.entry_price or ""),
                str(self.stop_loss or ""),
                ",".join(str(value) for value in self.take_profits),
            ]
        )
        return sha256(digest_source.encode("utf-8")).hexdigest()

    def first_take_profit(self) -> float | None:
        return self.take_profits[0] if self.take_profits else None


@dataclass(slots=True)
class TradeCommand:
    request_id: str
    source_group: str
    message_id: str
    symbol: str
    action: str
    order_type: str
    volume: float
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    take_profit_targets: list[float]
    submitted_at: str = field(default_factory=_now_iso)
    comment: str = ""

    @classmethod
    def from_signal(cls, signal: ParsedSignal, volume: float, comment_prefix: str = "TG Copier") -> "TradeCommand":
        if not signal.symbol or not signal.side:
            raise ValueError("Signal missing symbol or side")
        source_slug = _comment_source_slug(signal.source_group)[:16]
        message_suffix = str(signal.message_id)[-8:]
        return cls(
            request_id=str(uuid4()),
            source_group=signal.source_group,
            message_id=signal.message_id,
            symbol=signal.symbol,
            action=signal.side,
            order_type=signal.order_type,
            volume=volume,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.first_take_profit(),
            take_profit_targets=list(signal.take_profits),
            comment=f"TG|{source_slug}|{message_suffix}",
        )

    def to_bridge_payload(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "submitted_at": self.submitted_at,
            "submitted_epoch": _iso_to_epoch_text(self.submitted_at),
            "source_group": self.source_group,
            "message_id": self.message_id,
            "symbol": self.symbol,
            "action": self.action,
            "order_type": self.order_type,
            "volume": f"{self.volume:.2f}",
            "entry_price": "" if self.entry_price is None else str(self.entry_price),
            "stop_loss": "" if self.stop_loss is None else str(self.stop_loss),
            "take_profit": "" if self.take_profit is None else str(self.take_profit),
            "take_profit_targets": ",".join(str(value) for value in self.take_profit_targets),
            "comment": _normalize_text(self.comment),
        }

    def to_bridge_file(self) -> str:
        return "\n".join(f"{key}={value}" for key, value in self.to_bridge_payload().items()) + "\n"


@dataclass(slots=True)
class ExecutionResult:
    request_id: str
    status: str
    message: str
    ticket: str | None = None
    executed_price: float | None = None
    executed_at: str = field(default_factory=_now_iso)

    @classmethod
    def from_bridge_lines(cls, lines: Iterable[str]) -> "ExecutionResult":
        values: dict[str, str] = {}
        for line in lines:
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip()
        return cls(
            request_id=values.get("request_id", ""),
            status=values.get("status", "UNKNOWN"),
            message=values.get("message", ""),
            ticket=values.get("ticket") or None,
            executed_price=float(values["executed_price"]) if values.get("executed_price") else None,
            executed_at=values.get("executed_at", _now_iso()),
        )