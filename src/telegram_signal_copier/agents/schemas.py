"""Pydantic schemas shared across all agents in the LangGraph pipeline."""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
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
# Stage 1 output: LLM extraction result (strict, fails-safe)
# ---------------------------------------------------------------------------


class ExtractedSignal(BaseModel):
    """Raw signal as extracted by the LLM from unstructured text.

    All fields are deliberately Optional so the model returns a partial object
    rather than raising when the signal provider omits information.  The
    validation agent is responsible for rejecting incomplete signals.
    """

    symbol_raw: str | None = Field(
        default=None,
        description=(
            "Symbol or name as stated by the provider, e.g. 'Gold', 'XAU', 'EURUSD'."
        ),
    )
    side: Side | None = Field(
        default=None,
        description="Trade direction: BUY or SELL.",
    )
    order_type: OrderType = Field(
        default=OrderType.MARKET,
        description="Order type inferred from the message.",
    )
    entry_price: float | None = Field(
        default=None,
        description="Entry price. None for pure market orders.",
    )
    stop_loss: float | None = Field(
        default=None,
        description="Stop-loss level. Required for the signal to be tradeable.",
    )
    take_profits: list[Annotated[float, Field(gt=0)]] = Field(
        default_factory=list,
        description="One or more take-profit levels, ordered nearest first.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="LLM self-reported extraction confidence.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Extraction warnings or observations from the LLM.",
    )

    @model_validator(mode="after")
    def _clamp_confidence(self) -> "ExtractedSignal":
        self.confidence = max(0.0, min(1.0, self.confidence))
        return self


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


class ValidatedSignal(BaseModel):
    """Broker-ready payload produced by the Risk & Validation Agent."""

    # Mapped broker symbol (e.g. 'XAUUSD' from 'Gold')
    symbol: str
    side: Side
    order_type: OrderType
    entry_price: float | None
    stop_loss: float
    take_profits: list[float]
    volume: float = Field(default=0.01, gt=0)
    risk_reward_ratio: float = Field(default=0.0, ge=0)
    source_group: str = ""
    message_id: str = ""
    comment: str = ""

    @property
    def first_take_profit(self) -> float | None:
        return self.take_profits[0] if self.take_profits else None


# ---------------------------------------------------------------------------
# LangGraph shared state — flows through every node
# ---------------------------------------------------------------------------


class AgentState(BaseModel):
    """Mutable state dict that flows through the LangGraph pipeline.

    Each agent reads from and writes to this object.  Fields are all Optional
    so the state is valid at every intermediate stage.
    """

    # ── Input ──────────────────────────────────────────────────────────────
    raw_text: str = ""
    source_group: str = ""
    message_id: str = ""
    # Primary image path (local file) and all additional images for multi-chart signals
    image_path: str | None = None
    image_paths: list[str] = Field(default_factory=list)

    # ── Intent pre-filter ──────────────────────────────────────────────────
    intent: str | None = None          # NEW_SIGNAL | TRADE_UPDATE | INFORMATIONAL | UNKNOWN
    intent_confidence: float = 0.0

    # ── Stage 1: Extraction ────────────────────────────────────────────────
    extracted_signal: ExtractedSignal | None = None
    extraction_error: str | None = None

    # ── Stage 2: Validation ────────────────────────────────────────────────
    validated_signal: ValidatedSignal | None = None
    rejection_reasons: list[str] = Field(default_factory=list)

    # ── Stage 3: Execution ─────────────────────────────────────────────────
    execution_status: str | None = None  # "FILLED" | "SUBMITTED" | "REJECTED" | ...
    order_ticket: str | None = None
    execution_error: str | None = None

    # ── Routing flag set by each node ──────────────────────────────────────
    next_node: str = "extract"  # "extract" | "validate" | "execute" | "reject" | "end"

    model_config = {"arbitrary_types_allowed": True}
