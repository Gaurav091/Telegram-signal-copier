"""Backward-compatibility shim — heuristic_parse moved to services.signals.heuristic_parse."""
from telegram_signal_copier.services.signals.heuristic_parse import heuristic_parse as heuristic_parse  # noqa: F401
