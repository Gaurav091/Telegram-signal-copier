"""Main heuristic signal parser — rule-based text parsing without AI.

Extracted from signal_heuristic.py for maintainability.
Imports helpers from signal_heuristic (parse_cluster_context etc.).
"""
from __future__ import annotations

import re
import logging

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage
from telegram_signal_copier.services.signal_normalizers import (
    detect_order_type,
    detect_symbol_in_text,
    normalize_ocr_spaced_numbers,
    normalize_side,
)
from telegram_signal_copier.services.signal_patterns import (
    AT_SYMBOL_PATTERN,
    CLUSTER_BLOCK_RE,
    ENTRY_PATTERN,
    NEW_TRADE_CAPTIONS,
    PRICE_PATTERN,
    SL_PATTERN,
    SUPERSCRIPT_DIGIT_MAP,
    TARGET_LINE_PATTERN,
    TP_PATTERN,
)
from telegram_signal_copier.services.signals.heuristic import (
    parse_cluster_context,
    parse_mt5_screenshot,
)

logger = logging.getLogger(__name__)


def _maybe_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _first_float(values: list[str]) -> float | None:
    return float(values[0]) if values else None


def heuristic_parse(
    config: AppConfig,
    message: TelegramSignalMessage,
    combined_text: str,
) -> ParsedSignal:
    """Parse a trading signal from text using rule-based heuristics."""
    # OCR preprocessing: normalise thousands-space artifacts
    combined_text = normalize_ocr_spaced_numbers(combined_text)
    combined_text = combined_text.translate(SUPERSCRIPT_DIGIT_MAP)

    # MT5 position screenshot fast-path
    caption = (message.raw_text or "").strip()
    if NEW_TRADE_CAPTIONS.match(caption):
        screenshot = parse_mt5_screenshot(config, message, combined_text)
        if screenshot is not None:
            return screenshot

    upper_text = combined_text.upper()
    symbol = detect_symbol_in_text(upper_text, config.merged_allowed_symbols)
    side = normalize_side(
        "BUY" if "BUY" in upper_text or "LONG" in upper_text
        else "SELL" if "SELL" in upper_text or "SHORT" in upper_text
        else None
    )
    order_type = detect_order_type(upper_text)

    # Entry range support
    entry_range_low = None
    entry_range_high = None
    entry_price = None
    entry_range_match = re.search(r"(?:NEAR|AROUND)?\s*(\d{4,6})\s*[/\-]\s*(\d{4,6})", upper_text)
    if entry_range_match:
        first_val = float(entry_range_match.group(1))
        second_val = float(entry_range_match.group(2))
        entry_range_low = min(first_val, second_val)
        entry_range_high = max(first_val, second_val)
        entry_price = round((entry_range_low + entry_range_high) / 2, 2)
        if order_type == "MARKET":
            if side == "BUY":
                order_type = "BUY_LIMIT"
            elif side == "SELL":
                order_type = "SELL_LIMIT"
    else:
        for line in combined_text.splitlines():
            line_u = line.upper()
            if re.search(r"\b(ENTRY|AT|BUY|SELL|NOW|NEAR|AROUND)\b", line_u):
                pair = re.search(r"(\d{3,7})\s+(\d{3,7})", line_u)
                if pair:
                    try:
                        lo = float(pair.group(1))
                        hi = float(pair.group(2))
                        if lo >= 100 and hi >= 100:
                            entry_range_low = min(lo, hi)
                            entry_range_high = max(lo, hi)
                            entry_price = round((entry_range_low + entry_range_high) / 2, 2)
                            break
                    except Exception:
                        pass
        if entry_price is None:
            raw_entries = ENTRY_PATTERN.findall(upper_text)
            valid_entries = [v for v in raw_entries if _maybe_float(v) is not None and float(v) >= 100]
            entry_price = _first_float(valid_entries)
            if entry_price is None:
                raw_at = AT_SYMBOL_PATTERN.findall(upper_text)
                valid_at = [v for v in raw_at if _maybe_float(v) is not None and float(v) >= 100]
                entry_price = _first_float(valid_at)

    # SL/TP extraction (multi-line robust)
    stop_loss = None
    take_profits = []
    for line in combined_text.splitlines():
        line_u = line.upper()
        if not stop_loss:
            m = SL_PATTERN.search(line_u)
            if m:
                try:
                    stop_loss = float(m.group(1))
                except Exception:
                    pass
        tps = TP_PATTERN.findall(line_u)
        for tp in tps:
            try:
                tp_val = float(tp)
                if tp_val not in take_profits:
                    take_profits.append(tp_val)
            except Exception:
                pass
        target_line = TARGET_LINE_PATTERN.search(line_u)
        if target_line:
            for tp in PRICE_PATTERN.findall(target_line.group(1)):
                try:
                    tp_val = float(tp)
                    if tp_val >= 100 and tp_val not in take_profits:
                        take_profits.append(tp_val)
                except Exception:
                    pass

    if not take_profits:
        numbers = [float(value) for value in PRICE_PATTERN.findall(upper_text)]
        protected = {
            value
            for value in [entry_price, entry_range_low, entry_range_high, stop_loss]
            if value is not None
        }
        take_profits = [value for value in numbers if value not in protected][:3]

    # Overlay cluster-context levels (if MessageClusterAgent injected them)
    ctx = parse_cluster_context(combined_text)
    if ctx:
        symbol = ctx.get("symbol") or symbol
        side = normalize_side(ctx.get("side")) or side
        if ctx.get("order_type"):
            order_type = ctx["order_type"]
        if ctx.get("entry") is not None:
            entry_price = ctx["entry"]
        if ctx.get("sl") is not None:
            stop_loss = ctx["sl"]
        if ctx.get("tps"):
            take_profits = ctx["tps"]

    # Cap confidence when all levels come from cluster context with no message-own prices
    clean_msg_text = CLUSTER_BLOCK_RE.sub("", combined_text)
    msg_has_prices = bool(re.search(r"\d{3,6}", clean_msg_text))
    cluster_injected_levels = ctx and (ctx.get("sl") or ctx.get("entry") or ctx.get("tps"))
    cluster_only_levels = cluster_injected_levels and not msg_has_prices

    fields_found = sum(
        1
        for item in [symbol, side, order_type, entry_price, stop_loss, take_profits[0] if take_profits else None]
        if item not in (None, "")
    )
    confidence = min(0.35 if cluster_only_levels else 0.95, 0.25 + fields_found * 0.12)
    notes: list[str] = []
    if entry_range_low and entry_range_high:
        notes.append(f"Entry range detected: {entry_range_low}-{entry_range_high}, midpoint={entry_price}")
    if message.image_path:
        notes.append("Image attached; heuristic parser may need AI vision for full accuracy")
    if ctx:
        notes.append("Cluster context applied: " + "; ".join(f"{k}={v}" for k, v in ctx.items() if v))
    if cluster_only_levels:
        notes.append("WARN: message has no price numbers — cluster-context levels capped to low confidence")

    return ParsedSignal(
        source_group=message.source_group,
        message_id=message.message_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        entry_price=entry_price,
        entry_range_low=entry_range_low,
        entry_range_high=entry_range_high,
        stop_loss=stop_loss,
        take_profits=take_profits,
        confidence=confidence,
        raw_text=combined_text,
        image_used=bool(message.image_path),
        parser_name="heuristic",
        notes=notes,
    )
