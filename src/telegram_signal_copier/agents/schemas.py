"""Agent schemas — pure stdlib dataclasses, no external dependencies.

Replaces the previous pydantic-based models so the agent pipeline works
without ``pydantic``, ``langchain``, ``langgraph``, or the ``openai`` package.
All enumerations remain ``(str, Enum)`` so existing code using ``.value``
or string comparisons continues to work unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enumerations (stdlib — no change needed)
# ---------------------------------------------------------------------------


class OrderType(str, Enum):
    MARKET = "MARKET"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maybe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Stage 1 output: LLM extraction result
# ---------------------------------------------------------------------------


@dataclass
class ExtractedSignal:
    """Raw signal as extracted by the LLM from unstructured text.

    All fields are deliberately optional so the model returns a partial
    object rather than raising when the signal provider omits information.
    The validation agent is responsible for rejecting incomplete signals.
    """

    symbol_raw: str | None = None
    side: Side | None = None
    order_type: OrderType = OrderType.MARKET
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Clamp confidence to [0, 1]
        self.confidence = max(0.0, min(1.0, float(self.confidence or 0)))
        # Normalise side string → enum (LLM may return a plain string)
        if isinstance(self.side, str) and self.side:
            try:
                self.side = Side(self.side.strip().upper())
            except ValueError:
                self.side = None
        # Normalise order_type string → enum
        if isinstance(self.order_type, str):
            try:
                self.order_type = OrderType(self.order_type.strip().upper())
            except ValueError:
                self.order_type = OrderType.MARKET

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractedSignal":
        """Construct from a raw LLM JSON dict (permissive — never raises)."""
        tps = data.get("take_profits") or []
        if not isinstance(tps, list):
            tps = []
        notes = data.get("notes") or []
        if isinstance(notes, str):
            notes = [notes]
        return cls(
            symbol_raw=data.get("symbol_raw") or data.get("symbol"),
            side=data.get("side"),
            order_type=data.get("order_type", "MARKET") or "MARKET",
            entry_price=_maybe_float(data.get("entry_price")),
            stop_loss=_maybe_float(data.get("stop_loss")),
            take_profits=[float(v) for v in tps if v not in (None, "")],
            confidence=float(data.get("confidence") or 0),
            notes=[str(n) for n in notes],
        )

    # Alias used by code previously written against pydantic
    @classmethod
    def model_validate(cls, data: dict[str, Any]) -> "ExtractedSignal":
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Stage 2 output: Risk & Validation result
# ---------------------------------------------------------------------------


class RejectionReason(str, Enum):
    MISSING_SYMBOL = "MISSING_SYMBOL"
    MISSING_SIDE = "MISSING_SIDE"
    MISSING_SL = "MISSING_SL"
    MISSING_TP = "MISSING_TP"
    SYMBOL_NOT_ALLOWED = "SYMBOL_NOT_ALLOWED"
    INVALID_RR = "INVALID_RR"
    DUPLICATE = "DUPLICATE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INVALID_PRICE_RANGE = "INVALID_PRICE_RANGE"   # prices outside known symbol range
    STOP_TOO_CLOSE = "STOP_TOO_CLOSE"             # stop distance below broker minimum


@dataclass
class ValidatedSignal:
    """Broker-ready payload produced by the Risk & Validation Agent."""

    # Required fields — always supplied by the validation agent
    symbol: str
    side: Side
    stop_loss: float
    # Optional / defaulted fields
    order_type: OrderType = OrderType.MARKET
    entry_price: float | None = None
    take_profits: list[float] = field(default_factory=list)
    volume: float = 0.01
    risk_reward_ratio: float = 0.0
    source_group: str = ""
    message_id: str = ""
    comment: str = ""

    @property
    def first_take_profit(self) -> float | None:
        return self.take_profits[0] if self.take_profits else None

    @property
    def managed_take_profit(self) -> float | None:
        if len(self.take_profits) >= 2:
            return self.take_profits[1]
        return self.first_take_profit

    @property
    def final_take_profit(self) -> float | None:
        return self.take_profits[-1] if self.take_profits else None


# ---------------------------------------------------------------------------
# LangGraph shared state — flows through every node
# ---------------------------------------------------------------------------


@dataclass
class AgentState:
    """Mutable state that flows through every pipeline node.

    Each node receives the state, reads what it needs, and returns a
    ``dict`` of fields to update.  The pipeline merges those updates back
    into the state before invoking the next node.
    """

    # ── Input ──────────────────────────────────────────────────────────────
    raw_text: str = ""
    source_group: str = ""
    message_id: str = ""
    image_path: str | None = None
    image_paths: list[str] = field(default_factory=list)

    # ── Intent pre-filter ──────────────────────────────────────────────────
    intent: str | None = None
    intent_confidence: float = 0.0

    # ── Stage 1: Extraction ────────────────────────────────────────────────
    extracted_signal: ExtractedSignal | None = None
    extraction_error: str | None = None

    # ── Stage 2: Validation ────────────────────────────────────────────────
    validated_signal: ValidatedSignal | None = None
    rejection_reasons: list[str] = field(default_factory=list)

    # ── Stage 3: Execution ─────────────────────────────────────────────────
    execution_status: str | None = None
    order_ticket: str | None = None
    execution_error: str | None = None

    # ── Routing flag set by each node ──────────────────────────────────────
    next_node: str = "extract"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        """Build an AgentState from a partial-or-full dict (ignores unknown keys)."""
        known = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    # Alias kept for code previously written against pydantic
    @classmethod
    def model_validate(cls, data: dict[str, Any]) -> "AgentState":
        return cls.from_dict(data)

    def _apply(self, updates: dict[str, Any]) -> None:
        """Merge a partial update dict into this state in-place."""
        for k, v in updates.items():
            if hasattr(self, k):
                setattr(self, k, v)
