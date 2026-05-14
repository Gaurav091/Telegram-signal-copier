"""
MessageClusterAgent — Context-aware multi-message signal assembler.

Behavior
--------
* Receives flushed ``TelegramSignalMessage`` objects (already grouped by
  ``MessageBuffer``) for a source channel.
* Maintains a rolling cluster window per source (default 120 s).
  Within that window consecutive messages are combined into one context.
* Re-parses the combined cluster context to resolve multi-message patterns:

  Entry range (SELL):   "sell gold below 4707-4709"
  Follow-up targets:    "Target 4702-4695-4685"
  Follow-up SL:         "SL 4720" or "Stop 4720" in any message in the cluster

* When SL is absent but entry_range_high is known, auto-derives SL:
    SELL  → SL = entry_range_high + auto_sl_pips
    BUY   → SL = entry_range_low  - auto_sl_pips

* Emits a single synthetic ``TelegramSignalMessage`` whose ``raw_text``
  is the full cluster context, ready for the normal pipeline.

Configuration via env vars
--------------------------
CLUSTER_WINDOW_SECONDS      Rolling window to accumulate follow-up messages (default 120)
CLUSTER_AUTO_SL_PIPS        Pips added/subtracted beyond entry range for auto SL (default 20)
CLUSTER_ENABLED             "1"/"true" to enable (default "1")
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Regex helpers
# ──────────────────────────────────────────────────────────────────────────────

# "4707-4709" or "4707 - 4709" or "4707/4709"
_PRICE_RANGE_RE = re.compile(
    r"\b(\d{3,7}(?:\.\d{1,5})?)\s*[-/]\s*(\d{3,7}(?:\.\d{1,5})?)\b"
)

# "below 4707" / "above 4707" / "below 4707-4709"
_BELOW_ABOVE_RE = re.compile(
    r"\b(below|above|sell\s+below|buy\s+above|under|over)\s+"
    r"(\d{3,7}(?:\.\d{1,5})?)"
    r"(?:\s*[-/]\s*(\d{3,7}(?:\.\d{1,5})?))?",
    re.IGNORECASE,
)

# Target / TP follow-up:  "Target 4702-4695-4685" or "Target- 4702 4695 4685" or "TP: 4702 4695 4685"
_TARGET_RE = re.compile(
    r"(?:target|tp\s*\d*|take\s*profit\s*\d*)[:\s\-]+"
    r"((?:\d{3,7}(?:\.\d{1,5})?(?:\s*[-,/]\s*)?)+)",
    re.IGNORECASE,
)

# SL / Stop follow-up: "SL 4720" or "Stop 4720" or "Stop Loss 4720"
_SL_FOLLOW_RE = re.compile(
    r"(?:sl|stop\s*loss?|stoploss?)[:\s=]+(\d{3,7}(?:\.\d{1,5})?)",
    re.IGNORECASE,
)

# Single price number
_NUMBER_RE = re.compile(r"\b(\d{3,7}(?:\.\d{1,5})?)\b")


def _parse_price_list(text: str) -> list[float]:
    """Extract all price-like numbers from a fragment (e.g. '4702-4695-4685')."""
    return [float(m) for m in _NUMBER_RE.findall(text)]


# ──────────────────────────────────────────────────────────────────────────────
# Cluster parser
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ClusterSignal:
    """Structured extraction from a multi-message cluster."""
    symbol: str | None = None
    side: str | None = None
    entry_range_low: float | None = None
    entry_range_high: float | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    order_type: str = "MARKET"
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)


_SYMBOL_ALIASES: dict[str, str] = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAG": "XAGUSD",
    "OIL": "USOIL",
    "EU": "EURUSD",
    "GU": "GBPUSD",
    "UJ": "USDJPY",
    "DOW": "US30",
    "DJ30": "US30",
    "DOWJONES": "US30",
    "NDX": "NAS100",
    "NASDAQ": "NAS100",
    "NQ": "NAS100",
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
    "SP500": "SPX500",
}

_SIDE_WORDS = {
    "sell": "SELL",
    "short": "SELL",
    "buy": "BUY",
    "long": "BUY",
    "sell below": "SELL",
    "buy above": "BUY",
    "buy limit": "BUY",
    "sell limit": "SELL",
    "buy stop": "BUY",
    "sell stop": "SELL",
}

_ORDER_TYPE_MAP = {
    "sell below": "SELL_LIMIT",
    "buy above": "BUY_LIMIT",
    "sell limit": "SELL_LIMIT",
    "buy limit": "BUY_LIMIT",
    "buy stop": "BUY_STOP",
    "sell stop": "SELL_STOP",
}


def _detect_symbol(text: str) -> str | None:
    upper = text.upper()
    for alias, symbol in _SYMBOL_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", upper):
            return symbol
    # try known symbols directly
    for sym in ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "ETHUSD",
                "XAGUSD", "US30", "NAS100", "USOIL", "SPX500"):
        if sym in upper:
            return sym
    return None


def _detect_side_and_order_type(text: str) -> tuple[str | None, str]:
    lower = text.lower()
    for phrase in sorted(_ORDER_TYPE_MAP, key=len, reverse=True):
        if phrase in lower:
            return _SIDE_WORDS[phrase], _ORDER_TYPE_MAP[phrase]
    for word, side in sorted(_SIDE_WORDS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", lower):
            return side, "MARKET"
    return None, "MARKET"


def parse_cluster(texts: list[str], allowed_symbols: list[str] | None = None) -> ClusterSignal:
    """
    Combine a list of message texts into a single ClusterSignal.
    Texts are expected in chronological order (first message first).
    """
    sig = ClusterSignal()
    all_text = "\n".join(texts)
    combined_upper = all_text.upper()

    # ── Symbol ──────────────────────────────────────────────────────────────
    sig.symbol = _detect_symbol(all_text)
    if sig.symbol is None and allowed_symbols:
        for s in allowed_symbols:
            if s.upper() in combined_upper:
                sig.symbol = s.upper()
                break

    # ── Side + order type ───────────────────────────────────────────────────
    sig.side, sig.order_type = _detect_side_and_order_type(all_text)

    # ── Entry range / price ─────────────────────────────────────────────────
    # Look for "below X-Y" or "above X-Y" in each message
    for text in texts:
        m = _BELOW_ABOVE_RE.search(text)
        if m:
            qualifier = m.group(1).lower()
            low_str = m.group(2)
            high_str = m.group(3)
            low_val = float(low_str)
            high_val = float(high_str) if high_str else low_val
            # normalize: low ≤ high
            sig.entry_range_low = min(low_val, high_val)
            sig.entry_range_high = max(low_val, high_val)
            # entry_price: use upper bound for SELL, lower for BUY
            if sig.side == "SELL" or "below" in qualifier:
                sig.entry_price = sig.entry_range_high
                sig.order_type = "SELL_LIMIT"
                if not sig.side:
                    sig.side = "SELL"
            elif sig.side == "BUY" or "above" in qualifier:
                sig.entry_price = sig.entry_range_low
                sig.order_type = "BUY_LIMIT"
                if not sig.side:
                    sig.side = "BUY"
            sig.notes.append(
                f"Entry range [{sig.entry_range_low}–{sig.entry_range_high}] "
                f"→ entry_price={sig.entry_price} ({sig.order_type})"
            )
            break

    # Fallback: bare price range without qualifier
    if sig.entry_range_low is None:
        for text in texts[:1]:  # only first message for entry
            m = _PRICE_RANGE_RE.search(text)
            if m:
                a, b = float(m.group(1)), float(m.group(2))
                sig.entry_range_low = min(a, b)
                sig.entry_range_high = max(a, b)
                if sig.side == "SELL":
                    sig.entry_price = sig.entry_range_high
                elif sig.side == "BUY":
                    sig.entry_price = sig.entry_range_low

    # ── Take profits ─────────────────────────────────────────────────────────
    # Scan all texts for target/TP lines
    for text in texts:
        m = _TARGET_RE.search(text)
        if m:
            tp_list = _parse_price_list(m.group(1))
            if tp_list:
                sig.take_profits = tp_list
                sig.notes.append(f"TPs extracted from cluster follow-up: {tp_list}")
                break

    # ── Stop loss ─────────────────────────────────────────────────────────────
    for text in texts:
        m = _SL_FOLLOW_RE.search(text)
        if m:
            sig.stop_loss = float(m.group(1))
            sig.notes.append(f"SL extracted from cluster: {sig.stop_loss}")
            break

    # ── Confidence ────────────────────────────────────────────────────────────
    fields = [sig.symbol, sig.side, sig.entry_price, sig.stop_loss,
              sig.take_profits[0] if sig.take_profits else None]
    filled = sum(1 for f in fields if f is not None)
    sig.confidence = min(0.95, 0.20 + filled * 0.15)

    return sig


def auto_derive_sl(sig: ClusterSignal, auto_sl_pips: float = 20.0) -> ClusterSignal:
    """If SL is missing but entry range is present, compute SL from range + buffer."""
    if sig.stop_loss is not None:
        return sig
    # Estimate pip size: if price > 100 assume JPY-style (1 pip ≈ 0.01 * 100 = 1.0) or
    # metals (1 pip ≈ 0.1 or 1.0 depending on symbol).
    # For XAUUSD prices in 2000-3000 range, 1 pip ≈ 0.10 USD.
    # Use a simple heuristic: if price > 1000 → 1 pip = 1.0 USD; else → 1 pip = 0.0001
    ref = sig.entry_price or sig.entry_range_high or sig.entry_range_low
    if ref is None:
        return sig
    pip_size = 1.0 if ref > 100 else 0.0001
    buffer = auto_sl_pips * pip_size

    if sig.side == "SELL" and sig.entry_range_high is not None:
        sig.stop_loss = round(sig.entry_range_high + buffer, 5)
        sig.notes.append(
            f"Auto-derived SL={sig.stop_loss} (entry_range_high {sig.entry_range_high} + {auto_sl_pips} pips)"
        )
    elif sig.side == "BUY" and sig.entry_range_low is not None:
        sig.stop_loss = round(sig.entry_range_low - buffer, 5)
        sig.notes.append(
            f"Auto-derived SL={sig.stop_loss} (entry_range_low {sig.entry_range_low} - {auto_sl_pips} pips)"
        )
    return sig


# ──────────────────────────────────────────────────────────────────────────────
# Cluster accumulator
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _SourceCluster:
    messages: list[TelegramSignalMessage] = field(default_factory=list)
    last_updated: float = field(default_factory=time.monotonic)


class MessageClusterAgent:
    """
    Sits between the ``MessageBuffer`` flush and the ``CopierPipeline``.

    When a flushed message arrives:
    1. Append to the per-source cluster.
    2. Re-parse the whole cluster context.
    3. If the parsed result is more complete than any previous flush → emit
       a synthetic ``TelegramSignalMessage`` that enriches the original with
       cluster-derived levels.
    4. Expire stale clusters after ``window_seconds``.

    Usage::

        agent = MessageClusterAgent(config)
        # wrap the original on_message callback:
        async def on_message_with_cluster(msg):
            await agent.process(msg, original_on_message)
    """

    def __init__(
        self,
        allowed_symbols: list[str] | None = None,
        window_seconds: float | None = None,
        auto_sl_pips: float | None = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled and os.getenv("CLUSTER_ENABLED", "1").lower() in ("1", "true", "yes")
        self.window_seconds = window_seconds or float(os.getenv("CLUSTER_WINDOW_SECONDS", "120"))
        self.auto_sl_pips = auto_sl_pips or float(os.getenv("CLUSTER_AUTO_SL_PIPS", "20"))
        self.allowed_symbols = allowed_symbols or []
        self._clusters: dict[str, _SourceCluster] = defaultdict(_SourceCluster)
        self._lock = asyncio.Lock()

    async def process(
        self,
        message: TelegramSignalMessage,
        callback: Callable[[TelegramSignalMessage], Awaitable[None]],
    ) -> None:
        if not self.enabled:
            await callback(message)
            return

        async with self._lock:
            self._expire_stale()
            key = message.source_group
            cluster = self._clusters[key]
            cluster.messages.append(message)
            cluster.last_updated = time.monotonic()

            texts = [m.raw_text for m in cluster.messages if m.raw_text]
            sig = parse_cluster(texts, self.allowed_symbols)
            sig = auto_derive_sl(sig, self.auto_sl_pips)

            logger.info(
                "[CLUSTER] source=%s msgs=%d symbol=%s side=%s entry=%s SL=%s TP=%s conf=%.2f",
                key,
                len(cluster.messages),
                sig.symbol,
                sig.side,
                sig.entry_price,
                sig.stop_loss,
                sig.take_profits,
                sig.confidence,
            )

            enriched = self._enrich_message(message, sig)

        await callback(enriched)

    def _enrich_message(
        self, original: TelegramSignalMessage, sig: ClusterSignal
    ) -> TelegramSignalMessage:
        """
        Inject cluster-derived levels into raw_text as a structured header
        that the downstream heuristic/AI parser can pick up.
        """
        if not any([sig.symbol, sig.side, sig.entry_price, sig.stop_loss, sig.take_profits]):
            return original

        lines: list[str] = ["[CLUSTER CONTEXT]"]
        if sig.symbol:
            lines.append(f"Symbol: {sig.symbol}")
        if sig.side:
            lines.append(f"Side: {sig.side}")
        if sig.order_type and sig.order_type != "MARKET":
            lines.append(f"Order: {sig.order_type}")
        if sig.entry_range_low is not None and sig.entry_range_high is not None:
            lines.append(f"Entry range: {sig.entry_range_low}-{sig.entry_range_high}")
        if sig.entry_price is not None:
            lines.append(f"Entry: {sig.entry_price}")
        if sig.stop_loss is not None:
            lines.append(f"SL: {sig.stop_loss}")
        if sig.take_profits:
            lines.append("TP: " + " ".join(str(tp) for tp in sig.take_profits))
        for note in sig.notes:
            lines.append(f"# {note}")
        lines.append("[/CLUSTER CONTEXT]")

        cluster_header = "\n".join(lines)
        new_text = cluster_header + "\n---\n" + (original.raw_text or "")

        return TelegramSignalMessage(
            source_group=original.source_group,
            message_id=original.message_id,
            raw_text=new_text,
            image_path=original.image_path,
            sender=original.sender,
            received_at=original.received_at,
            all_image_paths=original.all_image_paths,
            grouped_count=original.grouped_count,
        )

    def _expire_stale(self) -> None:
        now = time.monotonic()
        stale = [k for k, v in self._clusters.items()
                 if now - v.last_updated > self.window_seconds]
        for k in stale:
            logger.debug("[CLUSTER] Expired cluster for source=%s", k)
            del self._clusters[k]

    def clear_source(self, source: str) -> None:
        self._clusters.pop(source, None)
