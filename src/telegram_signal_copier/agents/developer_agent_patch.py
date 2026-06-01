"""Backward-compatibility shim — developer agent patch moved to agents.developer.patch."""
from telegram_signal_copier.agents.developer.patch import (  # noqa: F401
    _call_llm as _call_llm,
    apply_patch as apply_patch,
    generate_patch as generate_patch,
    rollback_last_patch as rollback_last_patch,
)
