"""Developer Agent — shared models, constants, and category file mappings.

Extracted from developer_agent.py for maintainability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

MAX_FIXES_PER_SESSION = 10
_ALLOWED_PREFIX = "src/telegram_signal_copier/"
_BLOCKED_FILES = {
    "config.py",
    "schemas.py",
    "__init__.py",
}

# files that have already been fixed this session (path → times fixed)
_session_fix_counts: dict[str, int] = {}

# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------


@dataclass
class FailureReport:
    """Summary of a recurring pipeline failure pattern."""

    category: str
    count: int
    total_signals: int
    example_texts: list[str]
    rejection_reasons: list[str]
    execution_errors: list[str]
    description: str


@dataclass
class Patch:
    """A proposed code change."""

    file_path: str
    old_code: str
    new_code: str
    explanation: str


@dataclass
class FalsePositiveReport:
    """Result of evaluating whether a rejection rule is over-strict."""

    rejection_reason: str
    verdict: str
    count: int
    examples: list[str]
    llm_reasoning: str
    suggested_fix: str


# ---------------------------------------------------------------------------
# Category → source file mapping
# ---------------------------------------------------------------------------

_CATEGORY_FILES: dict[str, list[str]] = {
    "INTENT_UNKNOWN": [
        "src/telegram_signal_copier/agents/intent_filter.py",
    ],
    "PARSE_FAIL": [
        "src/telegram_signal_copier/agents/extraction_agent.py",
    ],
    "MISSING_SL": [
        "src/telegram_signal_copier/agents/extraction_agent.py",
        "src/telegram_signal_copier/agents/validation_agent.py",
    ],
    "MISSING_TP": [
        "src/telegram_signal_copier/agents/extraction_agent.py",
        "src/telegram_signal_copier/agents/validation_agent.py",
    ],
    "MISSING_SIDE": [
        "src/telegram_signal_copier/agents/extraction_agent.py",
    ],
    "LOW_RR": [
        "src/telegram_signal_copier/agents/validation_agent.py",
    ],
    "DUPLICATE_SIGNAL": [
        "src/telegram_signal_copier/agents/validation_agent.py",
    ],
    "INVALID_PRICE_RANGE": [
        "src/telegram_signal_copier/agents/validation_agent.py",
    ],
    "STOP_TOO_CLOSE": [
        "src/telegram_signal_copier/agents/validation_agent.py",
    ],
    "SYMBOL_NOT_ALLOWED": [
        "src/telegram_signal_copier/agents/validation_agent.py",
    ],
    "SYMBOL_NOT_MAPPED": [
        "src/telegram_signal_copier/agents/validation_agent.py",
    ],
    "EXECUTION_ERROR": [
        "src/telegram_signal_copier/agents/execution_agent.py",
        "src/telegram_signal_copier/adapters/bridge.py",
    ],
    "BRIDGE_TIMEOUT": [
        "src/telegram_signal_copier/adapters/bridge.py",
    ],
}
