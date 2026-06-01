"""Backward-compatibility shim — developer agent fp moved to agents.developer.fp."""
from telegram_signal_copier.agents.developer.fp import (  # noqa: F401
    assess_false_positives as assess_false_positives,
    fix_false_positives as fix_false_positives,
)
