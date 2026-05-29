"""Failure classification for the Developer Agent.

Extracted from developer_agent.py for maintainability.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from telegram_signal_copier.agents.developer_agent_models import FailureReport

logger = logging.getLogger(__name__)


def classify_failures(recent_logs: list[dict[str, Any]], window: int = 50) -> FailureReport | None:
    """Scan the last ``window`` pipeline log entries and return the dominant failure.

    Returns ``None`` if there are no actionable patterns (healthy or too few samples).
    """
    if not recent_logs:
        return None

    sample = recent_logs[-window:]
    total = len(sample)

    signals = [e for e in sample if e.get("intent") in ("NEW_SIGNAL", "UNKNOWN", None)]
    if not signals:
        return None

    rejected = [e for e in signals if e.get("action_taken") == "REJECTED"]
    failed_execution = [
        e for e in signals
        if e.get("action_taken") == "OPEN_TRADE"
        and e.get("execution_status") not in ("FILLED", "SUBMITTED", "DRY_RUN")
    ]

    reason_counter: Counter[str] = Counter()
    for e in rejected:
        for r in (e.get("rejection_reasons") or []):
            reason_counter[r] += 1

    unknown_count = sum(1 for e in signals if e.get("intent") in ("UNKNOWN", None) and not e.get("extraction"))

    extract_fail = sum(
        1 for e in signals
        if e.get("intent") == "NEW_SIGNAL"
        and not (e.get("extraction") or {}).get("symbol_raw")
        and not e.get("rejection_reasons")
    )

    failure_threshold = max(2, total // 4)

    if unknown_count >= failure_threshold:
        examples = _get_examples(signals, lambda e: e.get("intent") in ("UNKNOWN", None))
        return FailureReport(
            category="INTENT_UNKNOWN",
            count=unknown_count,
            total_signals=total,
            example_texts=examples,
            rejection_reasons=[],
            execution_errors=[],
            description=(
                f"{unknown_count}/{total} signals have intent=UNKNOWN — "
                "the intent filter is not recognising trade signals. "
                "Likely the LLM prompt or keyword heuristic needs updating."
            ),
        )

    if extract_fail >= failure_threshold:
        examples = _get_examples(
            signals,
            lambda e: e.get("intent") == "NEW_SIGNAL"
            and not (e.get("extraction") or {}).get("symbol_raw"),
        )
        return FailureReport(
            category="PARSE_FAIL",
            count=extract_fail,
            total_signals=total,
            example_texts=examples,
            rejection_reasons=[],
            execution_errors=[],
            description=(
                f"{extract_fail}/{total} signals with intent=NEW_SIGNAL have no extracted symbol — "
                "the extraction agent is failing to parse the signal text."
            ),
        )

    for reason_key, category in [
        ("missing_sl",           "MISSING_SL"),
        ("missing_tp",           "MISSING_TP"),
        ("missing_side",         "MISSING_SIDE"),
        ("invalid_price_range",  "INVALID_PRICE_RANGE"),
        ("stop_too_close",       "STOP_TOO_CLOSE"),
        ("low_rr",               "LOW_RR"),
        ("duplicate",            "DUPLICATE_SIGNAL"),
        ("symbol_not_allowed",   "SYMBOL_NOT_ALLOWED"),
        ("symbol_not_found",     "SYMBOL_NOT_MAPPED"),
        ("symbol_not_mapped",    "SYMBOL_NOT_MAPPED"),
    ]:
        cnt = sum(1 for r, c in reason_counter.items() if reason_key in r.lower() for _ in range(c))
        if cnt >= failure_threshold:
            examples = _get_examples(
                rejected, lambda e, k=reason_key: any(k in r.lower() for r in (e.get("rejection_reasons") or []))
            )
            reasons = [r for e in rejected for r in (e.get("rejection_reasons") or []) if reason_key in r.lower()]
            return FailureReport(
                category=category,
                count=cnt,
                total_signals=total,
                example_texts=examples,
                rejection_reasons=list(set(reasons))[:5],
                execution_errors=[],
                description=f"{cnt}/{total} signals rejected for '{reason_key}'. Examples: {reasons[:3]}",
            )

    if failed_execution:
        errors = [e.get("execution_error") or e.get("execution_status") for e in failed_execution]
        errors = [str(x) for x in errors if x]
        examples = _get_examples(failed_execution, lambda _: True)
        cat = "BRIDGE_TIMEOUT" if any("timeout" in (e or "").lower() for e in errors) else "EXECUTION_ERROR"
        return FailureReport(
            category=cat,
            count=len(failed_execution),
            total_signals=total,
            example_texts=examples,
            rejection_reasons=[],
            execution_errors=errors[:5],
            description=f"{len(failed_execution)}/{total} signals approved but execution failed: {errors[:3]}",
        )

    return None


def _get_examples(entries: list[dict], predicate) -> list[str]:
    texts = [
        e.get("text_snippet") or e.get("raw_text_snippet") or ""
        for e in entries
        if predicate(e) and (e.get("text_snippet") or e.get("raw_text_snippet"))
    ]
    return texts[:5]
