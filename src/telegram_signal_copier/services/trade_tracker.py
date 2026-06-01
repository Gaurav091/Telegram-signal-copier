"""Trade state tracker with JSON persistence.

Keeps a record of every trade opened by this system so that update messages
(TP hit, SL move, partial close, etc.) can reference the correct position.

State is persisted to a JSON file so it survives service restarts.
The file is written atomically to avoid corruption on crash.
Thread-safe via a ``threading.Lock``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TrackedTrade:
    """A single trade opened by the signal copier."""

    internal_id: str           # UUID assigned by this system
    symbol: str
    direction: str             # "buy" or "sell"
    entry_price: float
    lot_size: float
    opened_at: float           # Unix timestamp
    channel_id: int
    source_group_id: str       # MessageGroup.group_id that triggered this trade

    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    mt5_ticket: Optional[int] = None    # MT5 order ticket from .result file
    status: str = "open"                # "open" | "partial" | "closed"
    tp_levels_hit: List[int] = field(default_factory=list)
    notes: str = ""


class TradeTracker:
    """Manages open trade state with JSON-file persistence.

    Usage::

        tracker = TradeTracker(state_file=config.bridge_root / "trade_tracker_state.json")

        # Record a newly opened trade
        tracker.add_trade(TrackedTrade(...))

        # Find open trades on EURUSD buy
        trades = tracker.find_by_symbol_and_direction("EURUSD", "buy")

        # Mark a TP level hit
        tracker.update_trade(trade.internal_id, tp_levels_hit=[1], status="partial")
    """

    def __init__(self, state_file: str | Path) -> None:
        self._state_file = Path(state_file)
        self._lock = threading.Lock()
        self._trades: Dict[str, TrackedTrade] = {}
        self._load()

    # ── Write operations ──────────────────────────────────────────────────

    def add_trade(self, trade: TrackedTrade) -> None:
        with self._lock:
            self._trades[trade.internal_id] = trade
            self._save()
        logger.info(
            "[TRACKER] Added trade id=%s symbol=%s dir=%s entry=%.5f lot=%.2f",
            trade.internal_id, trade.symbol, trade.direction, trade.entry_price, trade.lot_size,
        )

    def update_trade(self, internal_id: str, **kwargs) -> bool:
        """Update fields on a tracked trade.  Returns True if the trade was found."""
        with self._lock:
            if internal_id not in self._trades:
                logger.warning("[TRACKER] update_trade: id=%s not found", internal_id)
                return False
            for key, value in kwargs.items():
                if hasattr(self._trades[internal_id], key):
                    setattr(self._trades[internal_id], key, value)
                else:
                    logger.warning("[TRACKER] update_trade: unknown field %r", key)
            self._save()
        logger.info("[TRACKER] Updated trade id=%s fields=%s", internal_id, list(kwargs))
        return True

    def close_trade(self, internal_id: str) -> bool:
        return self.update_trade(internal_id, status="closed")

    # ── Read operations ───────────────────────────────────────────────────

    def find_by_symbol_and_direction(
        self, symbol: str, direction: str
    ) -> List[TrackedTrade]:
        with self._lock:
            return [
                t for t in self._trades.values()
                if t.symbol.upper() == symbol.upper()
                and t.direction.lower() == direction.lower()
                and t.status in ("open", "partial")
            ]

    def find_most_recent_open(
        self, symbol: Optional[str] = None
    ) -> Optional[TrackedTrade]:
        with self._lock:
            candidates = [
                t for t in self._trades.values()
                if t.status in ("open", "partial")
            ]
            if symbol:
                candidates = [
                    t for t in candidates
                    if t.symbol.upper() == symbol.upper()
                ]
            if not candidates:
                return None
            return max(candidates, key=lambda t: t.opened_at)

    def get_all_open(self) -> List[TrackedTrade]:
        with self._lock:
            return [t for t in self._trades.values() if t.status in ("open", "partial")]

    def get_open_trades_summary(self) -> str:
        """JSON string suitable for injection into AI prompts."""
        with self._lock:
            data = [
                {
                    "id": t.internal_id,
                    "symbol": t.symbol,
                    "direction": t.direction,
                    "entry": t.entry_price,
                    "sl": t.sl,
                    "tp1": t.tp1,
                    "tp2": t.tp2,
                    "lot_size": t.lot_size,
                    "opened_at": t.opened_at,
                    "tp_levels_hit": t.tp_levels_hit,
                    "status": t.status,
                    "mt5_ticket": t.mt5_ticket,
                }
                for t in self._trades.values()
                if t.status in ("open", "partial")
            ]
        return json.dumps(data, indent=2)

    # ── Persistence ───────────────────────────────────────────────────────

    def _save(self) -> None:
        """Write state to disk atomically.  Must be called while holding self._lock."""
        data = {k: asdict(v) for k, v in self._trades.items()}
        tmp = self._state_file.with_suffix(self._state_file.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._state_file)
        except Exception:
            logger.exception("[TRACKER] Failed to save state to %s", self._state_file)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                logger.debug("Failed to remove temp file %s", tmp, exc_info=True)

    def _load(self) -> None:
        if not self._state_file.exists():
            return
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
            self._trades = {}
            for k, v in raw.items():
                try:
                    self._trades[k] = TrackedTrade(**v)
                except Exception as exc:
                    logger.warning("[TRACKER] Skipping corrupt trade record %r: %s", k, exc)
            logger.info("[TRACKER] Loaded %d trades from %s", len(self._trades), self._state_file)
        except Exception:
            logger.exception("[TRACKER] Failed to load state from %s — starting empty", self._state_file)
            self._trades = {}

    def prune_old_closed(self, keep_days: float = 7.0) -> int:
        """Remove closed trades older than ``keep_days`` days.  Returns count removed."""
        cutoff = time.time() - keep_days * 86400
        with self._lock:
            before = len(self._trades)
            self._trades = {
                k: v for k, v in self._trades.items()
                if v.status != "closed" or v.opened_at >= cutoff
            }
            removed = before - len(self._trades)
            if removed:
                self._save()
        if removed:
            logger.info("[TRACKER] Pruned %d old closed trades", removed)
        return removed
