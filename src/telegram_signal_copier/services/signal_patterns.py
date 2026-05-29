"""Regex patterns and constants for signal parsing.

Extracted from signal_parser.py for maintainability.
"""
from __future__ import annotations

import re

PRICE_PATTERN = re.compile(r"\b\d{1,6}(?:\.\d{1,5})?\b")
SL_PATTERN = re.compile(
    r"[✗❌✘⛔🚫]?\s*(?:\bSL\b|\bS\s*[\\/]\s*L\b|STOP\s*LOSS)\s*[.:=@-]?\s*(\d{1,6}(?:\.\d{1,5})?)",
    re.IGNORECASE,
)
TP_PATTERN = re.compile(
    r"(?:\bTP\d*\b|\bT\s*[\\/]\s*P\d*\b|TAKE\s*PROFIT\s*\d*)\s*[:=@-]?\s*(\d{1,6}(?:\.\d{1,5})?)",
    re.IGNORECASE,
)
TARGET_LINE_PATTERN = re.compile(r"\b(?:TARGETS?|TPS?)\b\s*[:=@-]?\s*(.+)", re.IGNORECASE)
ENTRY_PATTERN = re.compile(r"(?:ENTRY|AT|BUY|SELL)\s*[:=@-]?\s*(\d{1,6}(?:\.\d{1,5})?)", re.IGNORECASE)
AT_SYMBOL_PATTERN = re.compile(r"@\s*(\d{1,6}(?:\.\d{1,5})?)", re.IGNORECASE)

# MT5 open-position screenshot: "XAUUSD, sell 0.01" header line
MT5_SCREENSHOT_HEADER_RE = re.compile(
    r"^([A-Z0-9]{4,10}),\s*(buy|sell)\s+[\d.]+",
    re.IGNORECASE | re.MULTILINE,
)
# Normalise OCR thousands-space artifacts: "4 491.53" → "4491.53"
OCR_SPACE_NUMBER_RE = re.compile(r"(\d{1,4})\s+(\d{3}(?:[.,]\d+)?)(?=\D|$)")

# Map Unicode superscript digits (Tp¹, Tp², …) to ASCII equivalents
_SUPERSCRIPT_DIGIT_MAP = str.maketrans("¹²³⁴⁵⁶⁷⁸⁹⁰", "1234567890")

# Caption keywords that signal a new trade from ALGO TRADING forex-style groups
NEW_TRADE_CAPTIONS = re.compile(r"^\s*(new|both\s*new)\s*$", re.IGNORECASE)

# Cluster context block injected by MessageClusterAgent
CLUSTER_BLOCK_RE = re.compile(
    r"\[CLUSTER CONTEXT\](.*?)\[/CLUSTER CONTEXT\]",
    re.DOTALL | re.IGNORECASE,
)
CLUSTER_KV_RE = re.compile(r"^(\w[\w\s]*):\s*(.+)$", re.MULTILINE)

# Backward-compatible private aliases (keep existing names working)
_MT5_SCREENSHOT_HEADER_RE = MT5_SCREENSHOT_HEADER_RE
_OCR_SPACE_NUMBER_RE = OCR_SPACE_NUMBER_RE
_NEW_TRADE_CAPTIONS = NEW_TRADE_CAPTIONS
_CLUSTER_BLOCK_RE = CLUSTER_BLOCK_RE
_CLUSTER_KV_RE = CLUSTER_KV_RE

SUPERSCRIPT_DIGIT_MAP = _SUPERSCRIPT_DIGIT_MAP
