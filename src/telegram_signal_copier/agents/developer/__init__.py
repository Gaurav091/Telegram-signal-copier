"""Developer Agent — backward-compatible re-export shim.

All implementation has been split into focused submodules:
  developer_agent_models.py   — dataclasses, constants, _CATEGORY_FILES
  developer_agent_analysis.py — classify_failures, _get_examples
  developer_agent_fp.py       — assess_false_positives, fix_false_positives
  developer_agent_patch.py    — generate_patch, apply_patch, rollback_last_patch

All public symbols are re-exported here so existing imports continue to work.
"""
from __future__ import annotations

from telegram_signal_copier.agents.developer.analysis import (
    classify_failures,
    _get_examples,
)
from telegram_signal_copier.agents.developer.fp import (
    assess_false_positives,
    fix_false_positives,
)
from telegram_signal_copier.agents.developer.models import (
    FailureReport,
    FalsePositiveReport,
    MAX_FIXES_PER_SESSION,
    Patch,
    _ALLOWED_PREFIX,
    _BLOCKED_FILES,
    _CATEGORY_FILES,
    _session_fix_counts,
)
from telegram_signal_copier.agents.developer.patch import (
    apply_patch,
    generate_patch,
    rollback_last_patch,
)

__all__ = [
    "FailureReport",
    "FalsePositiveReport",
    "MAX_FIXES_PER_SESSION",
    "Patch",
    "apply_patch",
    "assess_false_positives",
    "classify_failures",
    "fix_false_positives",
    "generate_patch",
    "rollback_last_patch",
]
