"""Crypto entry price recovery and repair utilities.

Extracted from signal_parser.py for maintainability.
"""
from __future__ import annotations

import re
from typing import Any

from telegram_signal_copier.constants import CRYPTO_ENTRY_MIN
from telegram_signal_copier.services.signals.normalizers import normalize_ocr_spaced_numbers
from telegram_signal_copier.services.signals.patterns import ENTRY_PATTERN, PRICE_PATTERN


def recover_crypto_entry_from_text(
    symbol: str | None,
    side: str | None,
    text: str,
    stop_loss: float | None,
    take_profits: list[float],
) -> float | None:
    """Try to recover a crypto entry price from raw text when the AI got it wrong."""
    if not symbol or not text:
        return None

    base_symbol = symbol.upper().strip()
    min_expected = CRYPTO_ENTRY_MIN.get(base_symbol)
    if min_expected is None:
        return None

    normalized_text = normalize_ocr_spaced_numbers(text)

    # Prefer explicit entry wording when present (e.g. "Entry: 77645.45").
    labeled_entry = None
    for line in normalized_text.splitlines():
        line_upper = line.upper()
        if "ENTRY" not in line_upper:
            continue
        m = ENTRY_PATTERN.search(line_upper)
        if not m:
            continue
        try:
            labeled_entry = float(m.group(1))
        except Exception:
            labeled_entry = None
        if labeled_entry is not None:
            break

    if labeled_entry is not None and labeled_entry >= min_expected:
        if side == "BUY" and stop_loss is not None and stop_loss >= labeled_entry:
            labeled_entry = None
        if side == "SELL" and stop_loss is not None and stop_loss <= labeled_entry:
            labeled_entry = None
    if labeled_entry is not None:
        return labeled_entry

    candidates = []
    for raw in PRICE_PATTERN.findall(normalized_text.upper()):
        try:
            value = float(raw)
        except Exception:
            continue
        if value >= min_expected:
            candidates.append(value)
    if not candidates:
        return None

    anchors = [
        value
        for value in [stop_loss, *take_profits]
        if isinstance(value, (int, float)) and value > 0
    ]
    if not anchors:
        return None

    sorted_anchors = sorted(anchors)
    mid_anchor = sorted_anchors[len(sorted_anchors) // 2]

    best_value = None
    best_score = float("inf")
    for candidate in candidates:
        score = abs(candidate - mid_anchor)
        if side == "BUY" and stop_loss is not None and stop_loss >= candidate:
            score += 1_000_000
        if side == "SELL" and stop_loss is not None and stop_loss <= candidate:
            score += 1_000_000
        if take_profits:
            tp1 = take_profits[0]
            if side == "BUY" and tp1 <= candidate:
                score += 500_000
            if side == "SELL" and tp1 >= candidate:
                score += 500_000
        if score < best_score:
            best_score = score
            best_value = candidate

    return best_value


def repair_crypto_entry_price(
    symbol: str | None,
    side: str | None,
    entry_price: float | None,
    stop_loss: float | None,
    take_profits: list[float],
    notes: list[Any],
) -> float | None:
    """Correct an OCR-mangled crypto entry price using anchor levels (SL/TP)."""
    if entry_price is None or entry_price <= 0 or not symbol:
        return entry_price

    base_symbol = symbol.upper().strip()
    min_expected = CRYPTO_ENTRY_MIN.get(base_symbol)
    if min_expected is None or entry_price >= min_expected:
        return entry_price

    anchors = [
        value
        for value in [stop_loss, *take_profits]
        if isinstance(value, (int, float)) and value > 0
    ]
    if not anchors or not any(anchor >= min_expected for anchor in anchors):
        return entry_price

    entry_str = f"{entry_price:.5f}".rstrip("0").rstrip(".")
    int_part, _, _ = entry_str.partition(".")
    if not int_part.isdigit() or len(int_part) >= 5:
        return entry_price

    step = 10 ** len(int_part)

    sorted_anchors = sorted(anchors)
    mid_anchor = sorted_anchors[len(sorted_anchors) // 2]
    current_score = abs(entry_price - mid_anchor)
    best_value = entry_price
    best_score = current_score

    n_base = int(round((mid_anchor - entry_price) / step))
    for n in range(max(0, n_base - 8), n_base + 9):
        candidate = entry_price + (n * step)
        if candidate < min_expected:
            continue

        score = abs(candidate - mid_anchor)

        if side == "BUY" and stop_loss is not None and stop_loss >= candidate:
            score += 1_000_000
        if side == "SELL" and stop_loss is not None and stop_loss <= candidate:
            score += 1_000_000

        if take_profits:
            tp1 = take_profits[0]
            if side == "BUY" and tp1 <= candidate:
                score += 500_000
            if side == "SELL" and tp1 >= candidate:
                score += 500_000

        if score < best_score:
            best_score = score
            best_value = candidate

    if best_value != entry_price and best_score * 4 < current_score:
        notes.append(
            f"Adjusted entry from {entry_price} to {best_value} "
            f"using crypto anchor levels (SL/TP)"
        )
        return best_value
    return entry_price
