"""Cluster signal parsing — regex helpers and pure parsing logic.

Extracted from cluster_agent.py to keep each module under 300 lines.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ──────────────────────────────────────────────────────────────────────────────
# Regex patterns
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

# Target / TP follow-up: "Target 4702-4695-4685" or "TP: 4702 4695 4685"
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
# Data structures
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


# ──────────────────────────────────────────────────────────────────────────────
# Symbol / side lookup tables
# ──────────────────────────────────────────────────────────────────────────────

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

_SIDE_WORDS: dict[str, str] = {
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

_ORDER_TYPE_MAP: dict[str, str] = {
    "sell below": "SELL_LIMIT",
    "buy above": "BUY_LIMIT",
    "sell limit": "SELL_LIMIT",
    "buy limit": "BUY_LIMIT",
    "buy stop": "BUY_STOP",
    "sell stop": "SELL_STOP",
}


# ──────────────────────────────────────────────────────────────────────────────
# Detection helpers
# ──────────────────────────────────────────────────────────────────────────────

def _detect_symbol(text: str) -> str | None:
    upper = text.upper()
    for alias, symbol in _SYMBOL_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", upper):
            return symbol
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


# ──────────────────────────────────────────────────────────────────────────────
# Public parsing functions
# ──────────────────────────────────────────────────────────────────────────────

def parse_cluster(texts: list[str], allowed_symbols: list[str] | None = None) -> ClusterSignal:
    """Combine a list of message texts into a single ClusterSignal.

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
    for text in texts:
        m = _BELOW_ABOVE_RE.search(text)
        if m:
            qualifier = m.group(1).lower()
            low_val = float(m.group(2))
            high_val = float(m.group(3)) if m.group(3) else low_val
            sig.entry_range_low = min(low_val, high_val)
            sig.entry_range_high = max(low_val, high_val)
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

    if sig.entry_range_low is None:
        for text in texts[:1]:
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
