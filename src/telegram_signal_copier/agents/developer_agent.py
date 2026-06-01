"""Backward-compatibility shim — developer agent entry point moved to agents.developer."""
from telegram_signal_copier.agents.developer import (  # noqa: F401
    FailureReport as FailureReport,
    FalsePositiveReport as FalsePositiveReport,
    MAX_FIXES_PER_SESSION as MAX_FIXES_PER_SESSION,
    Patch as Patch,
    apply_patch as apply_patch,
    assess_false_positives as assess_false_positives,
    classify_failures as classify_failures,
    fix_false_positives as fix_false_positives,
    generate_patch as generate_patch,
    rollback_last_patch as rollback_last_patch,
)
