"""AI payload processing and signal merging for SignalParser.

Handles:
- AI payload → ParsedSignal conversion
- Range-aware AI/heuristic merge (_pick, entry digit reconstruction)
- TP direction consistency and MT5 screenshot authority
- Chart level supplementation for missing SL/TP
"""
from __future__ import annotations

from typing import Any

from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.constants import SYMBOL_PRICE_RANGES
from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage
from telegram_signal_copier.services.signals.normalizers import (
    maybe_float,
    normalize_side,
    normalize_symbol,
    strip_broker_suffix,
)


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
    confidence = maybe_float(payload.get("confidence"))
    return ParsedSignal(
        source_group=message.source_group,
        message_id=message.message_id,
        symbol=normalize_symbol(payload.get("symbol")),
        side=normalize_side(payload.get("side")),
        order_type=str(payload.get("order_type") or "MARKET").upper(),
        entry_price=maybe_float(payload.get("entry_price")),
        entry_range_low=maybe_float(payload.get("entry_range_low")),
        entry_range_high=maybe_float(payload.get("entry_range_high")),
        stop_loss=maybe_float(payload.get("stop_loss")),
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
    """Merge AI and heuristic signals with range-aware value selection."""
    allowed_bases = {strip_broker_suffix(s) for s in (config.merged_allowed_symbols or [])}
    symbol = ai_signal.symbol or heuristic_signal.symbol
    symbol_base = strip_broker_suffix(symbol)
    heuristic_base = strip_broker_suffix(heuristic_signal.symbol)
    if symbol and allowed_bases and symbol_base not in allowed_bases and heuristic_signal.symbol and heuristic_base in allowed_bases:
        symbol = heuristic_signal.symbol

    confidence = ai_signal.confidence if ai_signal.confidence > 0 else heuristic_signal.confidence
    notes = list(ai_signal.notes)
    for note in heuristic_signal.notes:
        if note not in notes:
            notes.append(note)
    if ai_signal.confidence <= 0 and heuristic_signal.confidence > 0:
        notes.append("AI confidence missing, reused heuristic confidence")

    _sym_for_range = symbol or ai_signal.symbol or heuristic_signal.symbol
    _plo, _phi = SYMBOL_PRICE_RANGES.get(_sym_for_range or "", (0.0, 999999.0))

    def _pick(preferred: float | None, fallback: float | None) -> float | None:
        if preferred is None:
            return fallback
        if fallback is not None and not (_plo <= preferred <= _phi) and (_plo <= fallback <= _phi):
            return fallback
        return preferred

    _entry = _pick(ai_signal.entry_price, heuristic_signal.entry_price)
    _sl = _pick(ai_signal.stop_loss, heuristic_signal.stop_loss)
    _side_merged = ai_signal.side or heuristic_signal.side

    # TP selection: prefer heuristic when AI TPs are suspect
    _ai_tps = ai_signal.take_profits or []
    _h_tps = heuristic_signal.take_profits or []
    if _ai_tps and _h_tps:
        _ai_valid = all(_plo <= t <= _phi for t in _ai_tps)
        _h_valid = all(_plo <= t <= _phi for t in _h_tps)

        def _tps_consistent(tps: list[float], side: str | None, entry: float | None, sl: float | None) -> bool:
            if not tps or side is None:
                return True
            ref = entry or sl
            if ref is None:
                return True
            if side == "SELL" and any(t >= ref for t in tps):
                return False
            if side == "BUY" and any(t <= ref for t in tps):
                return False
            return True

        _ai_ok = _tps_consistent(_ai_tps, _side_merged, _entry, _sl)
        _h_ok = _tps_consistent(_h_tps, _side_merged, _entry, _sl)
        _h_is_mt5 = heuristic_signal.parser_name == "mt5_screenshot"

        if _h_is_mt5 and _h_valid:
            _tps = _h_tps
            notes.append("MT5 screenshot parser overrode AI-extracted TPs (authoritative source)")
        elif (not _ai_valid or not _ai_ok) and (_h_valid and _h_ok):
            _tps = _h_tps
            notes.append("Used heuristic TPs (AI TPs inconsistent with signal direction/range)")
        else:
            _tps = _ai_tps
    else:
        _tps = _ai_tps or _h_tps

    # Entry digit reconstruction when AI dropped leading digits
    if (
        _entry is not None and _sym_for_range
        and not (_plo <= _entry <= _phi)
        and (_sl is not None or _tps)
    ):
        ref_prices = [p for p in ([_sl] + _tps) if p is not None and _plo <= p <= _phi]
        if ref_prices:
            ref = sum(ref_prices) / len(ref_prices)
            best_candidate: float | None = None
            best_dist = float("inf")
            _entry_str = str(_entry)
            for d1 in range(1, 10):
                v1 = float(f"{d1}{_entry_str}")
                if _plo <= v1 <= _phi:
                    d = abs(v1 - ref)
                    if d < best_dist:
                        best_dist, best_candidate = d, v1
                for d2 in range(0, 10):
                    v2 = float(f"{d1}{d2}{_entry_str}")
                    if _plo <= v2 <= _phi:
                        d = abs(v2 - ref)
                        if d < best_dist:
                            best_dist, best_candidate = d, v2
            candidate = best_candidate if best_candidate is not None else _entry
            if _plo <= candidate <= _phi:
                direction_ok = True
                if _side_merged == "BUY" and _sl is not None and candidate < _sl:
                    direction_ok = False
                if _side_merged == "SELL" and _sl is not None and candidate > _sl:
                    direction_ok = False
                if direction_ok:
                    notes.append(f"Adjusted entry {_entry}→{candidate} (leading digits recovered from SL/TP context)")
                    _entry = candidate

    h_parser = heuristic_signal.parser_name
    parser_name = f"openai+{h_parser}" if h_parser != "heuristic" else "openai+heuristic"

    return ParsedSignal(
        source_group=ai_signal.source_group,
        message_id=ai_signal.message_id,
        symbol=symbol,
        side=_side_merged,
        order_type=ai_signal.order_type or heuristic_signal.order_type,
        entry_price=_entry,
        entry_range_low=_pick(ai_signal.entry_range_low, heuristic_signal.entry_range_low),
        entry_range_high=_pick(ai_signal.entry_range_high, heuristic_signal.entry_range_high),
        stop_loss=_sl,
        take_profits=_tps,
        confidence=confidence,
        raw_text=ai_signal.raw_text,
        image_used=ai_signal.image_used or heuristic_signal.image_used,
        requires_review=ai_signal.requires_review,
        parser_name=parser_name,
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
