"""Algo Trading Forex trade-management helpers.

This module handles ALGO TRADING forex image captions that are not new entries:
- "Partial book" / "Partial" closes 50% of the matched position.
- "Partial book all" / "Partial both" / "Both partial" closes 50% of open
  XAUUSD and BTCUSD positions from the Algo source.

The feature is intentionally separate from signal parsing so title-less MT5
position-card updates are never treated as new trades.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Iterable

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ExecutionResult, TelegramSignalMessage
from telegram_signal_copier.models.contracts import _comment_source_slug
from telegram_signal_copier.services.signals.normalizers import strip_broker_suffix as _strip_broker_suffix
from telegram_signal_copier.services.signals.patterns import (
    ALGO_TRADE_UPDATE_CAPTIONS,
    MT5_SCREENSHOT_HEADER_RE,
    NEW_TRADE_CAPTIONS,
)

logger = logging.getLogger(__name__)

ALGO_SOURCE_SLUG = "ALGO-TRADING-FOR"
ALGO_SOURCE_COMMENT_PREFIX = f"TG|{ALGO_SOURCE_SLUG}|"
ALGO_PARTIAL_CLOSE_PERCENT = 50.0
ALGO_PARTIAL_SYMBOLS = {"XAUUSD", "BTCUSD"}

POSITION_TICKET_RE = re.compile(r"^\s*#\s*(\d{6,16})\s+Open\b", re.IGNORECASE | re.MULTILINE)
POSITION_TICKET_LABEL_RE = re.compile(r"\b(?:position|ticket|id)\s*[:#]?\s*(\d{6,16})\b", re.IGNORECASE)


@dataclass(slots=True)
class AlgoPosition:
    """Open MT5 position from the Algo source."""

    symbol: str
    ticket: int
    magic: int
    comment: str
    volume: float
    floating_profit: float = 0.0

    @property
    def symbol_base(self) -> str:
        return (_strip_broker_suffix(self.symbol) or self.symbol).upper()

    @property
    def is_algo_source(self) -> bool:
        return ALGO_SOURCE_COMMENT_PREFIX in self.comment

    def label(self) -> str:
        return f"{self.symbol} ticket={self.ticket} volume={self.volume:.2f} profit={self.floating_profit:.2f}"


@dataclass(slots=True)
class AlgoPartialClosePlan:
    """Parsed Algo partial-close intent from caption text."""

    action: str
    symbols: set[str] | None = None
    amount_usd: float | None = None
    profit_only: bool = False
    loss_only: bool = False
    reason: str = ""

    @property
    def is_no_action(self) -> bool:
        return self.action == "NO_ACTION"


def is_algo_trade_source(source_group: str) -> bool:
    """Return true for the configured ALGO TRADING forex source."""
    return _comment_source_slug(source_group)[:16] == ALGO_SOURCE_SLUG


def is_algo_new_trade_caption(raw_text: str) -> bool:
    """Only strict new-entry captions are allowed for Algo image signals."""
    return bool(NEW_TRADE_CAPTIONS.match(raw_text or ""))


def is_algo_partial_close_caption(raw_text: str) -> bool:
    """Return true for Algo partial-close management captions."""
    return bool(ALGO_TRADE_UPDATE_CAPTIONS.match(raw_text or ""))


def classify_algo_image_caption(raw_text: str) -> str:
    """Classify an Algo source caption before signal parsing."""
    caption = (raw_text or "").strip()
    if is_algo_new_trade_caption(caption):
        return "NEW_TRADE"
    if is_algo_partial_close_caption(caption):
        return "PARTIAL_CLOSE"
    return "NON_SIGNAL_UPDATE"


def parse_position_ticket_from_text(text: str) -> int | None:
    """Extract a position ticket from an MT5 position-card OCR text."""
    normalized = text or ""
    ticket_match = POSITION_TICKET_RE.search(normalized)
    if ticket_match:
        return int(ticket_match.group(1))

    for match in POSITION_TICKET_LABEL_RE.finditer(normalized):
        return int(match.group(1))
    return None


def extract_symbols_from_text(text: str) -> set[str]:
    """Extract broker symbols from OCR text."""
    symbols: set[str] = set()
    normalized = text or ""
    for match in MT5_SCREENSHOT_HEADER_RE.finditer(normalized):
        symbol = _strip_broker_suffix(match.group(1))
        if symbol:
            symbols.add(symbol.upper())

    upper = normalized.upper()
    for symbol in ALGO_PARTIAL_SYMBOLS:
        if re.search(rf"\b{symbol}\b", upper):
            symbols.add(symbol)
    return symbols


def load_algo_open_positions() -> tuple[list[AlgoPosition], str | None]:
    """Load open MT5 positions tagged by the Algo source comment."""
    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except Exception as exc:
        return [], f"MetaTrader5 package unavailable: {exc}"

    initialized = False
    try:
        if not mt5.initialize():
            last_error = mt5.last_error()
            return [], f"MT5 initialize failed: {last_error}"
        initialized = True

        records = mt5.positions_get() or []
        positions: list[AlgoPosition] = []
        for record in records:
            ticket = int(getattr(record, "ticket", 0) or 0)
            if ticket <= 0:
                continue
            comment = str(getattr(record, "comment", "") or "")
            if ALGO_SOURCE_COMMENT_PREFIX not in comment:
                continue
            positions.append(
                AlgoPosition(
                    symbol=str(getattr(record, "symbol", "") or ""),
                    ticket=ticket,
                    magic=int(getattr(record, "magic", 0) or 0),
                    comment=comment,
                    volume=float(getattr(record, "volume", 0.0) or 0.0),
                )
            )
        return positions, None
    except Exception as exc:
        return [], f"Failed to read MT5 positions: {exc}"
    finally:
        if initialized:
            try:
                mt5.shutdown()
            except Exception:
                logger.debug("MT5 shutdown failed", exc_info=True)


def _caption_closes_both(caption: str) -> bool:
    normalized = (caption or "").strip().lower()
    return "all" in normalized or "both" in normalized or "gold" in normalized and "btc" in normalized


def _caption_mentions_profit(caption: str) -> bool:
    return "profit" in (caption or "").strip().lower() or " usd" in (caption or "").strip().lower()


def _caption_mentions_loss(caption: str) -> bool:
    return "loss" in (caption or "").strip().lower()


def _caption_mentions_symbol(caption: str, symbol: str) -> bool:
    normalized = (caption or "").strip().lower()
    aliases = {
        "xauusd": ["xau", "xauusd", "gold"],
        "btcusd": ["btc", "btcusd"],
    }.get(symbol.lower(), [symbol.lower()])
    return any(alias in normalized for alias in aliases)


def _caption_mentions_symbol_any(caption: str, symbols: Iterable[str]) -> bool:
    return any(_caption_mentions_symbol(caption, symbol) for symbol in symbols)


def parse_algo_partial_close_caption(caption: str) -> AlgoPartialClosePlan:
    """Parse Algo partial-close captions into a simple execution plan."""
    text = (caption or "").strip()
    lower = text.lower()

    if not is_algo_partial_close_caption(text):
        return AlgoPartialClosePlan(action="NO_ACTION", reason="Caption is not an Algo partial-close management message")

    amount_match = re.search(r"(\d{2,5})\s*(?:usd|dollars?)\b", lower)
    amount = float(amount_match.group(1)) if amount_match else None

    symbols: set[str] | None = None
    if "all" in lower or "always" in lower or "both" in lower or ("gold" in lower and "btc" in lower):
        symbols = set(ALGO_PARTIAL_SYMBOLS)
    else:
        matched_symbols = {symbol for symbol in ALGO_PARTIAL_SYMBOLS if _caption_mentions_symbol(text, symbol)}
        if matched_symbols:
            symbols = matched_symbols

    if _caption_mentions_profit(text) and not _caption_mentions_loss(text):
        profit_only = True
    elif _caption_mentions_loss(text) and not _caption_mentions_profit(text):
        profit_only = False
        # Loss-only wording is still a partial-close action, not a full close.
        profit_only = False
    else:
        profit_only = False

    return AlgoPartialClosePlan(
        action="PARTIAL_CLOSE",
        symbols=symbols,
        amount_usd=amount,
        profit_only=profit_only,
        loss_only=_caption_mentions_loss(text) and not _caption_mentions_profit(text),
        reason="Parsed Algo partial-close caption",
    )


def select_positions_for_partial_close(
    caption: str,
    positions: Iterable[AlgoPosition],
    image_text: str = "",
) -> list[AlgoPosition]:
    """Select positions to close partially for an Algo management caption."""
    candidates = [position for position in positions if position.is_algo_source]
    if not candidates:
        return []

    plan = parse_algo_partial_close_caption(caption)
    if plan.is_no_action:
        return []

    if plan.symbols:
        filtered = [position for position in candidates if position.symbol_base in plan.symbols]
    else:
        filtered = candidates

    if plan.profit_only:
        filtered = [position for position in filtered if position.floating_profit > 0]
    if plan.loss_only:
        filtered = [position for position in filtered if position.floating_profit < 0]

    if filtered:
        return filtered

    ticket = parse_position_ticket_from_text(image_text)
    if ticket:
        return [position for position in candidates if position.ticket == ticket]

    symbols = extract_symbols_from_text(image_text)
    if symbols:
        return [position for position in candidates if position.symbol_base in symbols]

    return []


def execute_algo_partial_close(
    config: AppConfig,
    executor: FileBridgeExecutor,
    message: TelegramSignalMessage,
    image_text: str = "",
) -> ExecutionResult:
    """Execute 50% partial-close commands for Algo source management captions."""
    request_id = f"algo-partial-{message.message_id or 'unknown'}"
    caption = (message.raw_text or "").strip()

    if getattr(config, "dry_run", False):
        return ExecutionResult(
            request_id="dry-run",
            status="DRY_RUN",
            message="Dry run enabled; Algo partial-close command not sent",
        )

    positions, error = load_algo_open_positions()
    if error:
        return ExecutionResult(request_id=request_id, status="ERROR", message=error)

    selected = select_positions_for_partial_close(caption, positions, image_text=image_text)
    if not selected:
        return ExecutionResult(
            request_id=request_id,
            status="NO_POSITION",
            message="No matching Algo Trading Forex open positions found for partial close",
        )

    failures: list[str] = []
    closed_labels: list[str] = []
    for position in selected:
        result = executor.close_partial(
            symbol=position.symbol,
            ticket=position.ticket,
            close_percent=ALGO_PARTIAL_CLOSE_PERCENT,
            source_group=message.source_group,
            message_id=message.message_id,
            wait_for_result=True,
            timeout_seconds=getattr(config, "mt5_bridge_timeout_seconds", 60),
        )
        if result.status not in {"FILLED", "SUBMITTED", "PENDING"}:
            failures.append(f"{position.label()} -> {result.status}: {result.message}")
        else:
            closed_labels.append(position.label())

    if failures:
        return ExecutionResult(request_id=request_id, status="ERROR", message="; ".join(failures))

    return ExecutionResult(
        request_id=request_id,
        status="FILLED",
        message=f"Partial close {ALGO_PARTIAL_CLOSE_PERCENT:.0f}% executed for {len(closed_labels)} position(s): {', '.join(closed_labels)}",
    )
