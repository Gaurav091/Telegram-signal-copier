"""Heuristic signal parsing — rule-based extraction without AI.

Handles:
- MT5 screenshot fast-path
- Trade management / promo-spam early exits
- Symbol, side, order type detection (including custom keywords)
- Entry range detection and limit order inference
- SL/TP extraction (unicode, ellipsis, multi-target, TG shorthand)
- Cluster context overlay and noise guard
"""
from __future__ import annotations

import re
from typing import Any

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.constants import SYMBOL_PRICE_RANGES
from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage
from telegram_signal_copier.services.signals.patterns import (
    AT_SYMBOL_PATTERN,
    CLUSTER_BLOCK_RE,
    CLUSTER_KV_RE,
    ENTRY_PATTERN,
    MT5_SCREENSHOT_HEADER_RE,
    NEW_TRADE_CAPTIONS,
    OCR_SPACE_NUMBER_RE,
    PRICE_PATTERN,
    PROMO_SPAM_RE,
    SL_PATTERN,
    TARGET_MULTI_RE,
    TP_PATTERN,
    TRADE_MANAGEMENT_RE,
)
from telegram_signal_copier.services.signals.normalizers import (
    detect_order_type,
    detect_symbol_in_text,
    normalize_ocr_spaced_numbers,
    normalize_side,
)


def parse_cluster_context(text: str) -> dict | None:
    """Extract structured levels from a [CLUSTER CONTEXT] block if present."""
    m = CLUSTER_BLOCK_RE.search(text)
    if not m:
        return None
    block = m.group(1)
    result: dict[str, Any] = {}
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


def _parse_mt5_screenshot(
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

    clean = normalize_ocr_spaced_numbers(combined_text)

    entry_price: float | None = None
    stop_loss: float | None = None
    take_profits: list[float] = []
    
    # Single pass: extract S/L, T/P, and entry from MT5 screenshot format
    lines = clean.splitlines()
    for idx, line in enumerate(lines):
        line_upper = line.upper().strip()
        
        # --- S/L extraction: label on own line → skip blanks to find price ---
        if re.search(r"S[/\\]?L[.:]*\s*$", line_upper):
            for j in range(idx + 1, min(idx + 4, len(lines))):
                pm = re.search(r"^(\d{3,7}(?:\.\d{1,5})?)", lines[j].strip())
                if pm:
                    try:
                        stop_loss = float(pm.group(1))
                    except ValueError:
                        pass
                    break
            continue
        # S/L label + price on same line
        sl_m = re.search(r"(?:S[/\\]?L|STOP\s*LOSS)[.:\s]*(\d{3,7}(?:\.\d{1,5})?)", line_upper)
        if sl_m:
            try:
                stop_loss = float(sl_m.group(1))
            except ValueError:
                pass
        
        # --- T/P extraction: handles T/P:, T/P., T/P.:, TP: ---
        if re.search(r"T[/\\]?P[.:]*\s*$", line_upper):
            for j in range(idx + 1, min(idx + 4, len(lines))):
                pm = re.search(r"^(\d{3,7}(?:\.\d{1,5})?)", lines[j].strip())
                if pm:
                    try:
                        tp_val = float(pm.group(1))
                        if tp_val >= 100 and tp_val not in take_profits:
                            take_profits.append(tp_val)
                    except ValueError:
                        pass
                    break
            continue
        # T/P label + price on same line
        tp_m = re.search(r"(?:T[/\\]?P|TAKE\s*PROFIT)[.:\s]*(\d{3,7}(?:\.\d{1,5})?)", line_upper)
        if tp_m:
            try:
                tp_val = float(tp_m.group(1))
                if tp_val >= 100 and tp_val not in take_profits:
                    take_profits.append(tp_val)
            except ValueError:
                pass
        
        
        # --- Entry price: range pattern first, then labels ---
        if entry_price is None:
            range_m = re.search(r"(\d{3,7}(?:\.\d{1,5})?)\s*[-–—>]+\s*(\d{3,7}(?:\.\d{1,5})?)", line)
            if range_m:
                try:
                    p1, p2 = float(range_m.group(1)), float(range_m.group(2))
                    if p1 >= 100 and p2 >= 100:
                        entry_price = max(p1, p2)
                except Exception:
                    pass
            if entry_price is None:
                em = re.search(r"(?:ENTRY|PRICE)[:\s=]*@?\s*(\d{3,7}(?:\.\d{1,5})?)", line_upper)
                if em:
                    try:
                        val = float(em.group(1))
                        if val >= 100:
                            entry_price = val
                    except Exception:
                        pass
    
    # Fallback: pattern-based extraction for missed fields
    if stop_loss is None or not take_profits or entry_price is None:
        for line in clean.splitlines():
            if entry_price is None:
                em = re.search(r"(?:ENTRY|PRICE)[:\s=]*@?\s*(\d{3,7}(?:\.\d{1,5})?)", line, re.IGNORECASE)
                if em:
                    try:
                        entry_price = float(em.group(1))
                    except Exception:
                        pass
            if not stop_loss:
                m = SL_PATTERN.search(line)
                if m:
                    try:
                        val = float(m.group(1))
                        if val > 0:  # Reject negative values (swap/P&L artifacts)
                            stop_loss = val
                    except Exception:
                        pass
            for tp in TP_PATTERN.findall(line):
                try:
                    tp_val = float(tp)
                    if tp_val >= 100 and tp_val not in take_profits:
                        take_profits.append(tp_val)
                except Exception:
                    pass

    if not (symbol and side and (entry_price or stop_loss or take_profits)):
        return None

    fields_found = sum(
        1 for v in [symbol, side, entry_price, stop_loss, take_profits[0] if take_profits else None]
        if v not in (None, "")
    )
    confidence = min(0.95, 0.25 + fields_found * 0.12)
    mt5_notes = ["Parsed from MT5 position screenshot format"]
    if entry_price is not None:
        mt5_notes.append(f"Recovered entry from OCR text: {entry_price}")
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
        notes=mt5_notes,
    )


def heuristic_parse(
    config: AppConfig,
    message: TelegramSignalMessage,
    combined_text: str,
) -> ParsedSignal:
    """Rule-based signal extraction from text."""
    combined_text = normalize_ocr_spaced_numbers(combined_text)

    caption = (message.raw_text or "").strip()
    if NEW_TRADE_CAPTIONS.match(caption):
        screenshot = _parse_mt5_screenshot(config, message, combined_text)
        if screenshot is not None:
            return screenshot

    upper_text = combined_text.upper()

    if TRADE_MANAGEMENT_RE.search(combined_text):
        return ParsedSignal(
            source_group=message.source_group, message_id=message.message_id,
            symbol=None, side=None, order_type="MARKET",
            entry_price=None, stop_loss=None, take_profits=[],
            confidence=0.0, raw_text=combined_text,
            image_used=bool(message.image_path), parser_name="heuristic",
            notes=["Trade management message — not a new signal"],
        )

    if PROMO_SPAM_RE.search(combined_text):
        return ParsedSignal(
            source_group=message.source_group, message_id=message.message_id,
            symbol=None, side=None, order_type="MARKET",
            entry_price=None, stop_loss=None, take_profits=[],
            confidence=0.0, raw_text=combined_text,
            image_used=bool(message.image_path), parser_name="heuristic",
            notes=["Promo/spam message — not a trade signal"],
        )

    symbol = detect_symbol_in_text(upper_text, config.merged_allowed_symbols)

    _raw_side = (
        "BUY" if "BUY" in upper_text or "LONG" in upper_text
        else "SELL" if "SELL" in upper_text or "SHORT" in upper_text
        else None
    )
    if _raw_side is None:
        _custom_buy = [kw.upper() for kw in (getattr(config, "custom_buy_keywords", None) or [])]
        _custom_sell = [kw.upper() for kw in (getattr(config, "custom_sell_keywords", None) or [])]
        for kw in _custom_buy:
            if re.search(rf"\b{re.escape(kw)}\b", upper_text):
                _raw_side = "BUY"
                break
        if _raw_side is None:
            for kw in _custom_sell:
                if re.search(rf"\b{re.escape(kw)}\b", upper_text):
                    _raw_side = "SELL"
                    break
    side = normalize_side(_raw_side)
    order_type = detect_order_type(upper_text)

    entry_range_low: float | None = None
    entry_range_high: float | None = None
    entry_price: float | None = None

    entry_range_match = re.search(r"(?:NEAR|AROUND)?\s*(\d{4,6})\s*[/\-]\s*(\d{4,6})", upper_text)
    if entry_range_match:
        a, b = float(entry_range_match.group(1)), float(entry_range_match.group(2))
        entry_range_low = min(a, b)
        entry_range_high = max(a, b)
        entry_price = round((entry_range_low + entry_range_high) / 2, 2)
    else:
        for line in combined_text.splitlines():
            line_u = line.upper()
            if re.search(r"\b(ENTRY|AT|BUY|SELL|NOW|NEAR|AROUND)\b", line_u):
                pair = re.search(r"(\d{3,7})\s+(\d{3,7})", line_u)
                if pair:
                    try:
                        l_val, h_val = float(pair.group(1)), float(pair.group(2))
                        if l_val >= 100 and h_val >= 100:
                            entry_range_low, entry_range_high = l_val, h_val
                            entry_price = round((l_val + h_val) / 2, 2)
                            break
                    except Exception:
                        pass
    if entry_price is None:
        # Use symbol-aware minimum price to handle both XAUUSD (4000+) and forex pairs (1.0xxx)
        _entry_min = 0.1 if symbol and symbol in {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"} else 100.0
        raw_entries = ENTRY_PATTERN.findall(upper_text)
        valid = [v for v in raw_entries if _maybe_float(v) is not None and float(v) >= _entry_min]
        entry_price = _first_float(valid)
        if entry_price is None:
            raw_at = AT_SYMBOL_PATTERN.findall(upper_text)
            valid_at = [v for v in raw_at if _maybe_float(v) is not None and float(v) >= _entry_min]
            entry_price = _first_float(valid_at)

    stop_loss: float | None = None
    take_profits: list[float] = []
    _sym_range = SYMBOL_PRICE_RANGES.get(symbol or "", (0.0, 999999.0))
    _price_lo = max(0.0, _sym_range[0] * 0.3)
    _price_hi = _sym_range[1] * 2.0

    def _in_range(val: float) -> bool:
        return _price_lo <= val <= _price_hi

    tm = TARGET_MULTI_RE.search(combined_text)
    if tm:
        for rn in re.findall(r"\d{3,7}(?:\.\d{1,5})?", tm.group(1)):
            try:
                tv = float(rn)
                if _in_range(tv) and tv not in take_profits:
                    take_profits.append(tv)
            except Exception:
                pass

    lines = combined_text.splitlines()
    for idx, line in enumerate(lines):
        line_u = line.upper().strip()
        if not stop_loss:
            m = SL_PATTERN.search(line_u)
            if m:
                try:
                    sl_c = float(m.group(1))
                    if _in_range(sl_c):
                        stop_loss = sl_c
                except Exception:
                    pass
            # Multi-line SL: label on its own line, price on next line
            if not stop_loss and re.search(r"(?:^|\b)(?:SL|S\s*[\\/.]\s*L|STOP\s*LOSS)\s*[:=\-]?\s*$", line_u):
                for j in range(idx + 1, min(idx + 4, len(lines))):
                    pm = re.search(r"(\d{3,7}(?:\.\d{1,5})?)", lines[j].strip())
                    if pm:
                        try:
                            sl_c = float(pm.group(1))
                            if _in_range(sl_c):
                                stop_loss = sl_c
                        except Exception:
                            pass
                        break
        # Multi-line TP: label on its own line, price on next line
        if re.search(r"(?:^|\b)(?:TP\d*|T\s*[\\/.]\s*P\d*|TARGET\d*)\s*[:=\-]?\s*$", line_u):
            for j in range(idx + 1, min(idx + 4, len(lines))):
                pm = re.search(r"(\d{3,7}(?:\.\d{1,5})?)", lines[j].strip())
                if pm:
                    try:
                        tp_val = float(pm.group(1))
                        if _in_range(tp_val) and tp_val not in take_profits:
                            take_profits.append(tp_val)
                    except Exception:
                        pass
                    break
        for tp in TP_PATTERN.findall(line_u):
            try:
                tp_val = float(tp)
                if _in_range(tp_val) and tp_val not in take_profits:
                    take_profits.append(tp_val)
            except Exception:
                pass

    if not take_profits:
        numbers = [float(v) for v in PRICE_PATTERN.findall(upper_text)]
        protected = {v for v in [entry_price, entry_range_low, entry_range_high, stop_loss] if v is not None}
        take_profits = [v for v in numbers if v not in protected and _in_range(v)][1:3]

    if entry_range_low is not None and order_type == "MARKET":
        if side == "BUY":
            order_type = "BUY_LIMIT"
        elif side == "SELL":
            order_type = "SELL_LIMIT"

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

    _clean_msg = CLUSTER_BLOCK_RE.sub("", combined_text)
    _msg_has_prices = bool(re.search(r"\d{3,6}", _clean_msg))
    _cluster_injected = ctx and (ctx.get("sl") or ctx.get("entry") or ctx.get("tps"))
    _cluster_only = _cluster_injected and not _msg_has_prices

    # Core fields: symbol, side are essential; entry, SL, TP are trade levels
    core_fields = sum(
        1 for item in [symbol, side]
        if item not in (None, "")
    )
    level_fields = sum(
        1 for item in [entry_price, stop_loss, take_profits[0] if take_profits else None]
        if item not in (None, "")
    )
    fields_found = core_fields + level_fields

    # Base confidence from field count, but penalize when critical levels are missing
    if _cluster_only:
        confidence = min(0.35, 0.25 + fields_found * 0.12)
    elif core_fields >= 2 and level_fields >= 2:
        # Good signal: has symbol + side + at least 2 of (entry, SL, TP)
        confidence = min(0.95, 0.55 + fields_found * 0.08)
    elif core_fields >= 2 and level_fields >= 1:
        # Partial signal: has symbol + side + 1 level
        confidence = min(0.75, 0.40 + fields_found * 0.08)
    elif core_fields >= 2:
        # Minimal signal: has symbol + side only
        confidence = min(0.55, 0.30 + fields_found * 0.08)
    else:
        confidence = min(0.45, 0.25 + fields_found * 0.12)

    notes: list[str] = []
    if entry_range_low and entry_range_high:
        notes.append(f"Entry range detected: {entry_range_low}-{entry_range_high}, midpoint={entry_price}")
    if message.image_path:
        notes.append("Image attached; heuristic parser may need AI vision for full accuracy")
    if ctx:
        notes.append("Cluster context applied: " + "; ".join(f"{k}={v}" for k, v in ctx.items() if v))
    if _cluster_only:
        notes.append("WARN: message has no price numbers — cluster-context levels capped to low confidence")

    return ParsedSignal(
        source_group=message.source_group, message_id=message.message_id,
        symbol=symbol, side=side, order_type=order_type,
        entry_price=entry_price, entry_range_low=entry_range_low,
        entry_range_high=entry_range_high, stop_loss=stop_loss,
        take_profits=take_profits, confidence=confidence,
        raw_text=combined_text, image_used=bool(message.image_path),
        parser_name="heuristic", notes=notes,
    )


def _maybe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _first_float(values: list[str]) -> float | None:
    for v in values:
        f = _maybe_float(v)
        if f is not None:
            return f
    return None
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
