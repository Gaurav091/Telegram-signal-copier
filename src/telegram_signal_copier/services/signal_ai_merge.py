"""Backward-compatibility shim — ai_merge functions moved to services.signals.ai_merge."""
from telegram_signal_copier.services.signals.ai_merge import (  # noqa: F401
    fill_missing_levels_from_chart as fill_missing_levels_from_chart,
    from_ai_payload as from_ai_payload,
    merge_signals as merge_signals,
)
