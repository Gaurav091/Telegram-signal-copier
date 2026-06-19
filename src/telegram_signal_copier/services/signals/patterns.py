"""Regex patterns and constants for signal parsing.

Extracted from signal_parser.py for maintainability.
"""
from __future__ import annotations

import re

PRICE_PATTERN = re.compile(r"\b\d{1,7}(?:\.\d{1,5})?\b")
SL_PATTERN = re.compile(
    r"(?:[\u274c\u26a0\ufe0f\ud83d\udeab\u274e]*\s*)?"
    r"(?:\bSL\b|\bS\s*[\\/.]\s*L\b|STOP\s*LOSS|STOPLOSS|\bSTOP\b)"
    r"[\s:=@\-\u2026.]*\s*(\d{1,7}(?:\.\d{1,5})?)",
    re.IGNORECASE,
)
TP_PATTERN = re.compile(
    r"(?:[\u26a1\ufe0f\u2705\ud83c\udfaf\ud83d\udcb0]*\s*)?"
    r"(?:\bTP\d*\b|\bT\s*[\\/.]\s*P\d*\b|TAKE\s*PROFIT\s*\d*|\bTG\d*\b)"
    r"[\s:=@\-\u2026.]*\s*(\d{1,7}(?:\.\d{1,5})?)",
    re.IGNORECASE,
)
TARGET_LINE_PATTERN = re.compile(r"\b(?:TARGETS?|TPS?)\b\s*[:=@-]?\s*(.+)", re.IGNORECASE)
ENTRY_PATTERN = re.compile(r"(?:ENTRY|AT|BUY|SELL)\s*[:=@-]?\s*(\d{1,7}(?:\.\d{1,5})?)", re.IGNORECASE)
AT_SYMBOL_PATTERN = re.compile(r"@\s*(\d{1,7}(?:\.\d{1,5})?)", re.IGNORECASE)

# MT5 open-position screenshot: "XAUUSD, sell 0.01" header line
MT5_SCREENSHOT_HEADER_RE = re.compile(
    r"^([A-Z0-9]{4,10}),\s*(buy|sell)\s+[\d.]+",
    re.IGNORECASE | re.MULTILINE,
)
# Normalise OCR thousands-space artifacts: "4 491.53" → "4491.53"
OCR_SPACE_NUMBER_RE = re.compile(r"(\d{1,4})\s+(\d{3}(?:[.,]\d+)?)(?=\D|$)")

# Map Unicode superscript digits (Tp¹, Tp², …) to ASCII equivalents
_SUPERSCRIPT_DIGIT_MAP = str.maketrans("¹²³⁴⁵⁶⁷⁸⁹⁰", "1234567890")

# Caption keywords that signal a new trade from ALGO TRADING forex-style groups.
# Only these captions are allowed to turn an MT5 position screenshot into a new entry.
NEW_TRADE_CAPTIONS = re.compile(r"^\s*(?:new|both\s*new|btc\s*new)\s*$", re.IGNORECASE)

# Algo Trading Forex update captions: manage existing trades, not new entries.
# These prevent title-less MT5 position-card images from being treated as new trades.
# They intentionally allow loose provider wording such as "artial book", "profit booked",
# USD amounts, and trailing explanatory text after "Partial book.".
ALGO_TRADE_UPDATE_CAPTIONS = re.compile(
    r"^\s*(?:partial\s+in|partial\s+book(?:ed|ing)?(?:\s+[\w/.-]*)?|"
    r"partial\s+(?:in|into)?\s*(?:gold|xau(?:usd)?|btc(?:usd)?|both|all)?|"
    r"partial\s+(?:profit|loss)(?:\s+(?:book|booked))?(?:\s+(?:in|into)?\s*(?:gold|xau(?:usd)?|btc(?:usd)?|both|all))?|"
    r"\d{2,5}\s*(?:usd|dollars)?\s*profit\s+booked|"
    r"\d{2,5}\s*(?:usd|dollars?)\s+(?:partial\s+)?book(?:ed|ing)?|"
    r"always\s+partial\s+book\s+(?:profits?|loss(?:es)?)(?:\s*/\s*(?:profits?|loss(?:es)?))?\.?|"
    r"artial\s+book(?:ed|ing)?(?:\s+[\w/.-]*)?)\b.*$",
    re.IGNORECASE,
)

# Trade management messages — NOT new signals (move SL, hit TP, close position)
TRADE_MANAGEMENT_RE = re.compile(
    r"\b(?:move\s+sl|hit\s+tp|close\s+(?:position|trade|bad)|breakeven|bep|"
    r"trail\s+stop|partial\s+close|take\s+profit\s+hit|tp\d*\s+hit|"
    r"sl\s+to\s+(?:entry|be|breakeven)|secure\s+profit|"
    r"\d+\s*pips?\s*(?:running|done|booked|hit|achieved)|"
    r"\d+\s*(?:usd|dollars?)\s*(?:profit|done|booked)|"
    r"(?:profit|loss)\s*(?:booked|done|hitting|running)|"
    r"(?:all|both)\s*(?:tp|target)s?\s*(?:hit|done|achieved|complete)|"
    r"(?:tp|target)\s*\d?\s*(?:hit|done|achieved)|"
    r"(?:congratulat|well\s*done|nice\s*(?:trade|call|job))|"
    r"(?:hold|enjoy|ride|fly|flying|to\s*the\s*moon))\b",
    re.IGNORECASE,
)

# Promo/spam indicators — messages advertising VIP/groups rather than signals
PROMO_SPAM_RE = re.compile(
    r"\b(?:join\s+(?:my|our|the)?\s*(?:vip|group|channel)|free\s+trail|"
    r"hurry\s+up|add\s+\d+\s+members|dm\s+(?:me|for)|contact\s+(?:me|us)|"
    r"subscribe|paid\s+(?:group|signals|vip)|link\s+(?:will|won't)\s+work|"
    r"limited\s+(?:spots|time|offer))\b",
    re.IGNORECASE,
)

# Multi-target pattern: "Target- 4514, 4520, 4530" or "TP: 4514 4520 4530"
TARGET_MULTI_RE = re.compile(
    r"(?:target|tp\s*\d*|take\s*profit\s*\d*)[:\s\-]+"
    r"((?:\d{3,7}(?:\.\d{1,5})?(?:\s*[-,/\s]\s*)?)+)",
    re.IGNORECASE,
)

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
