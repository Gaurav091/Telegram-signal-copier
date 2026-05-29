"""AI payload processing and signal merging for SignalParser.

Extracted from signal_parser.py for maintainability.
"""
from __future__ import annotations

import logging
from typing import Any

from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.constants import CRYPTO_ENTRY_MIN
from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage
from telegram_signal_copier.services.signal_crypto import (
    recover_crypto_entry_from_text,
    repair_crypto_entry_price,
)
from telegram_signal_copier.services.signal_normalizers import (
    maybe_float,
    normalize_side,
    normalize_symbol,
    strip_broker_suffix,
)

logger = logging.getLogger(__name__)

# Backward-compatible alias
_CRYPTO_ENTRY_MIN = CRYPTO_ENTRY_MIN


def from_ai_payload(
    message: TelegramSignalMessage,
    combined_text: str,
    payload: dict[str, Any],
) -> ParsedSignal:
    """Build a ParsedSignal from an AI JSON payload."""
    raw_take_profits = payload.get("take_profits") or []
    if not isinstance(raw_take_profits, list):
        raw_take_profits = []
    take_profits = [float(value) for value in raw_take_profits if value not in (None, "")]
    notes = payload.get("notes") or []
    if isinstance(notes, str):
        notes = [notes]
    symbol = normalize_symbol(payload.get("symbol"))
    side = normalize_side(payload.get("side"))
    entry_price = maybe_float(payload.get("entry_price"))
    stop_loss = maybe_float(payload.get("stop_loss"))
    recovered_entry = recover_crypto_entry_from_text(
        symbol=symbol,
        side=side,
        text=combined_text,
        stop_loss=stop_loss,
        take_profits=take_profits,
    )
    if recovered_entry is not None:
        min_expected = _CRYPTO_ENTRY_MIN.get((symbol or "").upper())
        if (
            entry_price is None
            or (min_expected is not None and entry_price < min_expected)
            or abs(recovered_entry - entry_price) > 1000
        ):
            notes.append(f"Recovered entry from OCR text: {entry_price} -> {recovered_entry}")
            entry_price = recovered_entry
    entry_price = repair_crypto_entry_price(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profits=take_profits,
        notes=notes,
    )
    confidence = maybe_float(payload.get("confidence"))
    return ParsedSignal(
        source_group=message.source_group,
        message_id=message.message_id,
        symbol=symbol,
        side=side,
        order_type=str(payload.get("order_type") or "MARKET").upper(),
        entry_price=entry_price,
        entry_range_low=maybe_float(payload.get("entry_range_low")),
        entry_range_high=maybe_float(payload.get("entry_range_high")),
        stop_loss=stop_loss,
        take_profits=take_profits,
        confidence=max(0.0, min(1.0, confidence if confidence is not None else 0.0)),
        raw_text=combined_text,
        image_used=bool(message.image_path),
        requires_review=False,
        parser_name="openai",
        notes=[str(note) for note in notes],
    )


def merge_signals(
    config: AppConfig,
    ai_signal: ParsedSignal,
    heuristic_signal: ParsedSignal,
) -> ParsedSignal:
    """Merge AI-parsed and heuristic-parsed signals, preferring AI values."""
    allowed_bases = {strip_broker_suffix(symbol) for symbol in (config.merged_allowed_symbols or [])}
    symbol = ai_signal.symbol or heuristic_signal.symbol
    symbol_base = strip_broker_suffix(symbol)
    heuristic_base = strip_broker_suffix(heuristic_signal.symbol)
    if symbol and allowed_bases and (symbol_base not in allowed_bases) and heuristic_signal.symbol and heuristic_base in allowed_bases:
        symbol = heuristic_signal.symbol

    confidence = ai_signal.confidence if ai_signal.confidence > 0 else heuristic_signal.confidence
    notes = list(ai_signal.notes)
    for note in heuristic_signal.notes:
        if note not in notes:
            notes.append(note)
    if ai_signal.confidence <= 0 and heuristic_signal.confidence > 0:
        notes.append("AI confidence missing, reused heuristic confidence")

    if heuristic_signal.parser_name == "mt5_screenshot":
        overridden_fields: list[str] = []
        if heuristic_signal.entry_price is not None and ai_signal.entry_price != heuristic_signal.entry_price:
            overridden_fields.append("entry")
        if heuristic_signal.stop_loss is not None and ai_signal.stop_loss != heuristic_signal.stop_loss:
            overridden_fields.append("stop_loss")
        if heuristic_signal.take_profits and ai_signal.take_profits != heuristic_signal.take_profits:
            overridden_fields.append("take_profits")
        if overridden_fields:
            notes.append("MT5 screenshot parser overrode AI-extracted " + ", ".join(overridden_fields))

        return ParsedSignal(
            source_group=ai_signal.source_group,
            message_id=ai_signal.message_id,
            symbol=heuristic_signal.symbol or symbol,
            side=heuristic_signal.side or ai_signal.side,
            order_type=heuristic_signal.order_type or ai_signal.order_type,
            entry_price=heuristic_signal.entry_price if heuristic_signal.entry_price is not None else ai_signal.entry_price,
            entry_range_low=heuristic_signal.entry_range_low if heuristic_signal.entry_range_low is not None else ai_signal.entry_range_low,
            entry_range_high=heuristic_signal.entry_range_high if heuristic_signal.entry_range_high is not None else ai_signal.entry_range_high,
            stop_loss=heuristic_signal.stop_loss if heuristic_signal.stop_loss is not None else ai_signal.stop_loss,
            take_profits=heuristic_signal.take_profits or ai_signal.take_profits,
            confidence=max(ai_signal.confidence, heuristic_signal.confidence),
            raw_text=ai_signal.raw_text,
            image_used=ai_signal.image_used or heuristic_signal.image_used,
            requires_review=ai_signal.requires_review or heuristic_signal.requires_review,
            parser_name="openai+mt5_screenshot",
            notes=notes,
        )

    return ParsedSignal(
        source_group=ai_signal.source_group,
        message_id=ai_signal.message_id,
        symbol=symbol,
        side=ai_signal.side or heuristic_signal.side,
        order_type=ai_signal.order_type or heuristic_signal.order_type,
        entry_price=ai_signal.entry_price if ai_signal.entry_price is not None else heuristic_signal.entry_price,
        entry_range_low=ai_signal.entry_range_low if ai_signal.entry_range_low is not None else heuristic_signal.entry_range_low,
        entry_range_high=ai_signal.entry_range_high if ai_signal.entry_range_high is not None else heuristic_signal.entry_range_high,
        stop_loss=ai_signal.stop_loss if ai_signal.stop_loss is not None else heuristic_signal.stop_loss,
        take_profits=ai_signal.take_profits or heuristic_signal.take_profits,
        confidence=confidence,
        raw_text=ai_signal.raw_text,
        image_used=ai_signal.image_used or heuristic_signal.image_used,
        requires_review=ai_signal.requires_review,
        parser_name="openai+heuristic",
        notes=notes,
    )


def fill_missing_levels_from_chart(
    ai_client: OpenAIClient | None,
    signal: ParsedSignal,
    message: TelegramSignalMessage,
) -> ParsedSignal:
    """Fill missing SL/TP by querying the AI to analyze a chart image."""
    if not message.image_path:
        return signal
    needs_sl = signal.stop_loss is None
    needs_tp = not signal.take_profits
    if not needs_sl and not needs_tp:
        return signal
    if not ai_client:
        return signal
    try:
        levels = ai_client.extract_chart_levels(
            image_path=message.image_path,
            symbol=signal.symbol,
            side=signal.side,
            entry_price=signal.entry_price,
        )
        chart_sl = maybe_float(levels.get("stop_loss"))
        raw_tps = levels.get("take_profits") or []
        if not isinstance(raw_tps, list):
            raw_tps = []
        chart_tps = [float(v) for v in raw_tps if v not in (None, "")]
        chart_confidence = max(0.0, min(1.0, float(levels.get("confidence") or 0)))

        if chart_confidence < 0.30:
            signal.notes.append(
                f"Chart level extraction confidence too low ({chart_confidence:.2f}), skipped"
            )
            return signal

        filled: list[str] = []
        if needs_sl and chart_sl is not None:
            signal = ParsedSignal(
                source_group=signal.source_group, message_id=signal.message_id,
                symbol=signal.symbol, side=signal.side, order_type=signal.order_type,
                entry_price=signal.entry_price, entry_range_low=signal.entry_range_low,
                entry_range_high=signal.entry_range_high, stop_loss=chart_sl,
                take_profits=signal.take_profits, confidence=signal.confidence,
                raw_text=signal.raw_text, image_used=True, requires_review=True,
                parser_name=signal.parser_name, notes=signal.notes,
            )
            filled.append(f"SL {chart_sl} (from chart)")
        if needs_tp and chart_tps:
            signal = ParsedSignal(
                source_group=signal.source_group, message_id=signal.message_id,
                symbol=signal.symbol, side=signal.side, order_type=signal.order_type,
                entry_price=signal.entry_price, entry_range_low=signal.entry_range_low,
                entry_range_high=signal.entry_range_high, stop_loss=signal.stop_loss,
                take_profits=chart_tps, confidence=signal.confidence,
                raw_text=signal.raw_text, image_used=True, requires_review=True,
                parser_name=signal.parser_name, notes=signal.notes,
            )
            filled.append(f"TPs {chart_tps} (from chart)")
        if filled:
            signal.notes.append(f"Chart image supplemented missing levels: {', '.join(filled)}")
    except Exception as exc:
        signal.notes.append(f"Chart level extraction failed: {exc}")
    return signal
