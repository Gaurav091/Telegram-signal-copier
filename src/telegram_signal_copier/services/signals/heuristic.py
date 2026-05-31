"""Heuristic signal parsing functions.

Extracted from signal_parser.py for maintainability.
These functions parse signals from text without AI assistance.
"""
from __future__ import annotations

import re
import logging

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage
from telegram_signal_copier.services.signal_normalizers import (
    detect_symbol_in_text,
    detect_order_type,
    normalize_side,
    normalize_ocr_spaced_numbers,
)
from telegram_signal_copier.services.signal_patterns import (
    CLUSTER_BLOCK_RE,
    CLUSTER_KV_RE,
    MT5_SCREENSHOT_HEADER_RE,
    NEW_TRADE_CAPTIONS,
    OCR_SPACE_NUMBER_RE,
    PRICE_PATTERN,
    SL_PATTERN,
    TP_PATTERN,
)

logger = logging.getLogger(__name__)


def parse_cluster_context(text: str) -> dict | None:
    """Extract structured levels from a [CLUSTER CONTEXT] block if present."""
    m = CLUSTER_BLOCK_RE.search(text)
    if not m:
        return None
    block = m.group(1)
    result: dict = {}
    for kv in CLUSTER_KV_RE.finditer(block):
        key = kv.group(1).strip().lower()
        val = kv.group(2).strip()
        if key == "symbol":
            result["symbol"] = val
        elif key == "side":
            result["side"] = val
        elif key == "order":
            result["order_type"] = val
        elif key == "entry":
            try:
                result["entry"] = float(val)
            except ValueError:
                pass
        elif key == "sl":
            try:
                result["sl"] = float(val)
            except ValueError:
                pass
        elif key == "tp":
            nums = re.findall(r"\d{3,7}(?:\.\d{1,5})?", val)
            result["tps"] = [float(n) for n in nums]
    return result if result else None


def extract_mt5_screenshot_entry_candidates(clean_text: str) -> list[float]:
    """Return all price candidates from the MT5 screenshot entry line (after the header)."""
    header_seen = False
    for raw_line in clean_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not header_seen:
            if MT5_SCREENSHOT_HEADER_RE.search(line):
                header_seen = True
            continue

        upper_line = line.upper()
        if any(token in upper_line for token in ("OPEN:", "S/L", "SL", "T/P", "TP", "COMMENT:", "SWAP")):
            break

        candidates: list[float] = []
        for value in PRICE_PATTERN.findall(line):
            try:
                price = float(value)
            except Exception:
                continue
            if price >= 100:
                candidates.append(price)
        if candidates:
            return candidates

    return []


def parse_mt5_screenshot(
    config: AppConfig,
    message: TelegramSignalMessage,
    combined_text: str,
) -> ParsedSignal | None:
    """Parse an MT5 open-position screenshot."""
    header = MT5_SCREENSHOT_HEADER_RE.search(combined_text)
    if not header:
        return None

    symbol = detect_symbol_in_text(header.group(1).upper(), config.merged_allowed_symbols)
    side = normalize_side(header.group(2))

    clean = OCR_SPACE_NUMBER_RE.sub(lambda m: m.group(1) + m.group(2), combined_text)
    entry_candidates = extract_mt5_screenshot_entry_candidates(clean)
    entry_price = entry_candidates[0] if entry_candidates else None

    stop_loss: float | None = None
    take_profits: list[float] = []
    for line in clean.splitlines():
        if not stop_loss:
            m = SL_PATTERN.search(line)
            if m:
                try:
                    stop_loss = float(m.group(1))
                except Exception:
                    pass
        for tp in TP_PATTERN.findall(line):
            try:
                tp_val = float(tp)
                if tp_val >= 100 and tp_val not in take_profits:
                    take_profits.append(tp_val)
            except Exception:
                pass

    if not (symbol and side and (stop_loss or take_profits)):
        return None

    if (
        entry_price is not None
        and len(entry_candidates) > 1
        and stop_loss is not None
        and take_profits
    ):
        tp1 = take_profits[0]
        is_inverted = (
            (side == "BUY" and (entry_price <= stop_loss or entry_price >= tp1))
            or (side == "SELL" and (entry_price >= stop_loss or entry_price <= tp1))
        )
        if is_inverted:
            for cand in entry_candidates[1:]:
                if side == "BUY" and stop_loss < cand < tp1:
                    entry_price = cand
                    break
                if side == "SELL" and tp1 < cand < stop_loss:
                    entry_price = cand
                    break

    fields_found = sum(
        1 for v in [symbol, side, entry_price, stop_loss, take_profits[0] if take_profits else None]
        if v not in (None, "")
    )
    confidence = min(0.95, 0.25 + fields_found * 0.12)
    notes = ["Parsed from MT5 position screenshot format"]
    if entry_price is not None:
        notes.append(f"Entry inferred from MT5 screenshot price line: {entry_price}")
    return ParsedSignal(
        source_group=message.source_group,
        message_id=message.message_id,
        symbol=symbol,
        side=side,
        order_type="MARKET",
        entry_price=entry_price,
        entry_range_low=None,
        entry_range_high=None,
        stop_loss=stop_loss,
        take_profits=take_profits,
        confidence=confidence,
        raw_text=combined_text,
        image_used=bool(message.image_path),
        parser_name="mt5_screenshot",
        notes=notes,
    )


# Re-export: callers that imported heuristic_parse from this module continue to work
from telegram_signal_copier.services.signal_heuristic_parse import heuristic_parse as heuristic_parse  # noqa: E402, F401
