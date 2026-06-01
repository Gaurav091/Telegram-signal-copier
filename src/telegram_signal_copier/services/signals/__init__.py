"""Services/signals sub-package — signal parsing, normalisation, patterns, and heuristics."""
from telegram_signal_copier.services.signals.parser import SignalParser as SignalParser, ParseResult as ParseResult  # noqa: F401
from telegram_signal_copier.services.signals.normalizers import (  # noqa: F401
    normalize_symbol as normalize_symbol,
    normalize_side as normalize_side,
    normalize_ocr_spaced_numbers as normalize_ocr_spaced_numbers,
    maybe_float as maybe_float,
    first_float as first_float,
    detect_order_type as detect_order_type,
    strip_broker_suffix as strip_broker_suffix,
    detect_symbol_in_text as detect_symbol_in_text,
)
