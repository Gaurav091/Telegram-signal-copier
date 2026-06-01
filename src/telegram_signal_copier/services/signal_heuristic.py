"""Backward-compatibility shim — heuristic_parse moved to services.signals.heuristic_parse."""
from telegram_signal_copier.services.signals.heuristic_parse import heuristic_parse as heuristic_parse  # noqa: F401
from telegram_signal_copier.services.signals.heuristic import (  # noqa: F401
    extract_mt5_screenshot_entry_candidates as extract_mt5_screenshot_entry_candidates,
    parse_cluster_context as parse_cluster_context,
    parse_mt5_screenshot as parse_mt5_screenshot,
)
