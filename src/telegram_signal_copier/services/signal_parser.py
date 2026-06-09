"""Backward-compatible facade — delegates to signals/ subpackage.

All imports from this module continue to work unchanged.
Actual implementation lives in:
  signals.parser      — SignalParser, ParseResult
  signals.heuristic   — heuristic_parse, parse_cluster_context
  signals.ai_merge    — from_ai_payload, merge_signals, fill_missing_levels_from_chart
  signals.patterns    — regex constants
  signals.normalizers — normalization utilities
"""
from __future__ import annotations

# Re-export everything that external code imports from this module
from telegram_signal_copier.services.signals.parser import (  # noqa: F401
    ParseResult as ParseResult,
    SignalParser as SignalParser,
)
from telegram_signal_copier.services.signals.patterns import (  # noqa: F401
    PRICE_PATTERN as PRICE_PATTERN,
    SL_PATTERN as SL_PATTERN,
    TP_PATTERN as TP_PATTERN,
    ENTRY_PATTERN as ENTRY_PATTERN,
    AT_SYMBOL_PATTERN as AT_SYMBOL_PATTERN,
    CLUSTER_BLOCK_RE as _CLUSTER_BLOCK_RE,
    CLUSTER_KV_RE as _CLUSTER_KV_RE,
    TARGET_MULTI_RE as _TARGET_MULTI_RE,
    TRADE_MANAGEMENT_RE as _TRADE_MANAGEMENT_RE,
    PROMO_SPAM_RE as _PROMO_SPAM_RE,
)
from telegram_signal_copier.services.signals.heuristic import (  # noqa: F401
    heuristic_parse as _heuristic_parse_fn,
    parse_cluster_context as _parse_cluster_context_fn,
)
from telegram_signal_copier.services.signals.ai_merge import (  # noqa: F401
    from_ai_payload as _from_ai_payload_fn,
    merge_signals as _merge_signals_fn,
    fill_missing_levels_from_chart as _fill_missing_levels_from_chart_fn,
)
