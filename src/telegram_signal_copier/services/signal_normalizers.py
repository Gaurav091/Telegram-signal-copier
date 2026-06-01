"""Backward-compatibility shim — normalizer functions moved to services.signals.normalizers."""
from telegram_signal_copier.services.signals.normalizers import (  # noqa: F401
    detect_order_type as detect_order_type,
    detect_symbol_in_text as detect_symbol_in_text,
    first_float as first_float,
    maybe_float as maybe_float,
    normalize_ocr_spaced_numbers as normalize_ocr_spaced_numbers,
    normalize_side as normalize_side,
    normalize_symbol as normalize_symbol,
    strip_broker_suffix as strip_broker_suffix,
)
