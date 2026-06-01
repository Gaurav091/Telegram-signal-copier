"""Backward-compatibility shim — SignalParser moved to services.signals.parser."""
from telegram_signal_copier.services.signals.parser import ParseResult as ParseResult, SignalParser as SignalParser  # noqa: F401
