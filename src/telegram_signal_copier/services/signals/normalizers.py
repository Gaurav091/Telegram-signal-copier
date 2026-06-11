"""Static normalizer utilities for signal parsing.

Extracted from signal_parser.py for maintainability.
"""
from __future__ import annotations

import re
from typing import Any

from telegram_signal_copier.services.signal_patterns import OCR_SPACE_NUMBER_RE


def normalize_symbol(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().upper()
    aliases = {
        "GOLD": "XAUUSD",
        "XAU": "XAUUSD",
        "EU": "EURUSD",
        "GU": "GBPUSD",
        "UJ": "USDJPY",
        "DOW": "US30",
        "DJ30": "US30",
        "DOWJONES": "US30",
        "NDX": "NAS100",
        "NASDAQ": "NAS100",
        "NQ": "NAS100",
    }
    return aliases.get(normalized, normalized)


def normalize_side(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    if normalized == "LONG":
        return "BUY"
    if normalized == "SHORT":
        return "SELL"
    return normalized if normalized in {"BUY", "SELL"} else None


def normalize_ocr_spaced_numbers(text: str) -> str:
    if not text:
        return text
    return OCR_SPACE_NUMBER_RE.sub(lambda m: m.group(1) + m.group(2), text)


def maybe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_float(values: list[str]) -> float | None:
    return float(values[0]) if values else None


def detect_order_type(upper_text: str) -> str:
    for candidate in ["BUY LIMIT", "SELL LIMIT", "BUY STOP", "SELL STOP"]:
        if candidate in upper_text:
            return candidate.replace(" ", "_")
    return "MARKET"


def strip_broker_suffix(symbol: str | None) -> str | None:
    if not symbol:
        return None
    s = str(symbol).strip().upper()
    for suf in ('.M', '-M', 'M'):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def detect_symbol_in_text(upper_text: str, allowed_symbols: list[str], strict: bool = False) -> str | None:
    """Detect a trading symbol in upper-cased text.

    Checks common aliases first, then configured allowed symbols,
    then falls back to a regex for tokens that look like instrument codes.
    
    Args:
        strict: If True, skip fallback regex (use for OCR text to prevent garbage matches).
    """
    aliases = {
        "GOLD": "XAUUSD",
        "XAU": "XAUUSD",
        "EU": "EURUSD",
        "GU": "GBPUSD",
        "UJ": "USDJPY",
        "DOW": "US30",
        "DJ30": "US30",
        "DOWJONES": "US30",
        "US 30": "US30",
        "NDX": "NAS100",
        "NASDAQ": "NAS100",
        "NAS 100": "NAS100",
        "NQ": "NAS100",
    }
    for alias, symbol in aliases.items():
        if re.search(rf"\b{re.escape(alias)}\b", upper_text):
            return symbol
    for symbol in allowed_symbols:
        normalized = str(symbol).upper()
        # Use word boundary to prevent substring matches on OCR garbage
        if re.search(rf"\b{re.escape(normalized)}\b", upper_text):
            return normalized
        if re.search(rf"\b{re.escape(normalized)}M\b", upper_text) or re.search(rf"\b{re.escape(normalized)}\.M\b", upper_text):
            return normalized
    if strict:
        return None
    match = re.search(r"\b([A-Z0-9]{3,10}(?:\d+|USD|EUR|JPY|GBP|AUD|CAD|NZD|CHF|XAU|XAG))\b", upper_text)
    return match.group(1) if match else None
