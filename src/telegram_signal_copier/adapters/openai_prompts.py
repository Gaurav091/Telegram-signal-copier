"""Backward-compatibility shim — prompt constants moved to adapters.ai.prompts."""
from telegram_signal_copier.adapters.ai.prompts import (  # noqa: F401
    CLASSIFY_INTENT_SYSTEM_PROMPT as CLASSIFY_INTENT_SYSTEM_PROMPT,
    EXTRACT_CHART_LEVELS_SYSTEM_PROMPT as EXTRACT_CHART_LEVELS_SYSTEM_PROMPT,
    PARSE_SIGNAL_SYSTEM_PROMPT as PARSE_SIGNAL_SYSTEM_PROMPT,
    boost_system_prompt,
)
