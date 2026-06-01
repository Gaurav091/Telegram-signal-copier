"""Backward-compatibility shim — developer agent analysis moved to agents.developer.analysis."""
from telegram_signal_copier.agents.developer.analysis import (  # noqa: F401
    classify_failures as classify_failures,
    _get_examples as _get_examples,
)
