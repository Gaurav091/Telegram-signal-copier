"""Backward-compatibility shim — developer agent models moved to agents.developer.models."""
from telegram_signal_copier.agents.developer.models import (  # noqa: F401
    FailureReport as FailureReport,
    FalsePositiveReport as FalsePositiveReport,
    MAX_FIXES_PER_SESSION as MAX_FIXES_PER_SESSION,
    Patch as Patch,
    _ALLOWED_PREFIX as _ALLOWED_PREFIX,
    _BLOCKED_FILES as _BLOCKED_FILES,
    _CATEGORY_FILES as _CATEGORY_FILES,
    _session_fix_counts as _session_fix_counts,
)
