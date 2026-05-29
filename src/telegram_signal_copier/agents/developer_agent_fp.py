"""False-positive rejection analysis for the Developer Agent.

Extracted from developer_agent.py for maintainability.
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any
from pathlib import Path

from telegram_signal_copier.agents.developer_agent_models import (
    FailureReport,
    FalsePositiveReport,
    MAX_FIXES_PER_SESSION,
)

logger = logging.getLogger(__name__)


def _load_relevant_sources_for_reason(reason_key: str, repo_root: Path) -> dict[str, str]:
    """Load source files relevant to a rejection reason key."""
    from telegram_signal_copier.agents.developer_agent_models import _CATEGORY_FILES
    rel_paths = _CATEGORY_FILES.get(reason_key, [])
    result: dict[str, str] = {}
    for rp in rel_paths:
        abs_p = repo_root / rp
        if not abs_p.exists():
            continue
        try:
            result[rp] = abs_p.read_text(encoding="utf-8")
        except Exception:
            pass
    return result


def _build_false_positive_prompt(
    reason_key: str,
    entry_context: str,
    source_files: dict[str, str],
) -> str:
    sources_block = "\n\n".join(
        f"=== FILE: {path} ===\n{code}" for path, code in source_files.items()
    )
    return f"""You are an expert Forex/Gold trading system developer reviewing automatic trade rejections.

## REJECTION CATEGORY UNDER REVIEW
Rule: {reason_key}

## REJECTED SIGNALS (with extracted prices)
{entry_context}

## CURRENT VALIDATION SOURCE CODE
{sources_block}

## YOUR TASK
Determine whether the '{reason_key}' validation rule is **too strict** and is incorrectly blocking valid trades.

Consider:
1. Are the extracted prices reasonable for the symbol (e.g. XAUUSD at 3300–3500, NAS100 at 17000–22000)?
2. Is the rejection threshold correctly configured, or is it miscalibrated?
3. Would a professional Forex broker accept this trade setup?
4. Is the rule protecting against a genuine risk, or is it a false guard?

## RESPONSE FORMAT (JSON only, no markdown)
{{"verdict": "FALSE_POSITIVE", "reasoning": "One or two sentence explanation", "suggested_fix": "Concrete description of what threshold/condition to change"}}

OR: {{"verdict": "CORRECT_REJECTION", "reasoning": "Why the rejection is valid", "suggested_fix": ""}}
OR: {{"verdict": "UNCERTAIN", "reasoning": "Why it is unclear", "suggested_fix": ""}}

Respond with ONLY the JSON. No markdown fences. No preamble."""


def _parse_false_positive_response(response: str) -> dict | None:
    try:
        text = response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(text)
        if "verdict" not in data:
            return None
        data["verdict"] = data["verdict"].strip().upper()
        if data["verdict"] not in ("FALSE_POSITIVE", "CORRECT_REJECTION", "UNCERTAIN"):
            data["verdict"] = "UNCERTAIN"
        return data
    except Exception as exc:
        logger.debug("[DEV_AGENT] Failed to parse FP response: %s", exc)
        return None


def assess_false_positives(
    rejected_entries: list[dict],
    repo_root: Path,
    llm_client: Any,
    min_count: int = 2,
) -> list[FalsePositiveReport]:
    """Examine rejected pipeline log entries and determine if any validation
    rules are over-strict (i.e. blocking valid trades)."""
    if not rejected_entries:
        return []

    by_reason: dict[str, list[dict]] = defaultdict(list)
    for entry in rejected_entries:
        reasons = entry.get("rejection_reasons") or []
        for r in reasons:
            key = r.split(":")[0].replace("RejectionReason.", "").strip().upper()
            by_reason[key].append(entry)
            break

    from telegram_signal_copier.agents.developer_agent_patch import _call_llm

    reports: list[FalsePositiveReport] = []
    for reason_key, entries in by_reason.items():
        if len(entries) < min_count:
            continue

        examples = [
            (e.get("text_snippet") or e.get("raw_text_snippet") or "")[:250]
            for e in entries[:6]
            if (e.get("text_snippet") or e.get("raw_text_snippet"))
        ]

        source_files = _load_relevant_sources_for_reason(reason_key, repo_root)
        if not source_files:
            fp = repo_root / "src/telegram_signal_copier/agents/validation_agent.py"
            if fp.exists():
                source_files = {
                    "src/telegram_signal_copier/agents/validation_agent.py":
                    fp.read_text(encoding="utf-8")
                }

        entry_contexts = []
        for e in entries[:6]:
            ext = e.get("extraction") or {}
            entry_contexts.append(
                f"  signal: {(e.get('text_snippet') or '')[:150]!r}\n"
                f"  extracted: symbol={ext.get('symbol_raw')!r}  side={ext.get('side')!r}"
                f"  entry={ext.get('entry_price')}  sl={ext.get('stop_loss')}  tps={ext.get('take_profits')}\n"
                f"  rejection: {e.get('rejection_reasons')}"
            )
        context_block = "\n---\n".join(entry_contexts) or "(no extraction context available)"

        prompt = _build_false_positive_prompt(reason_key, context_block, source_files)

        logger.info("[DEV_AGENT] Assessing FP for rejection reason=%s (%d examples)", reason_key, len(entries))
        try:
            response = _call_llm(llm_client, prompt)
        except Exception as exc:
            logger.warning("[DEV_AGENT] LLM call failed for FP assessment (%s): %s", reason_key, exc)
            continue

        result = _parse_false_positive_response(response)
        if result is None:
            continue

        reports.append(FalsePositiveReport(
            rejection_reason=reason_key,
            verdict=result.get("verdict", "UNCERTAIN"),
            count=len(entries),
            examples=examples,
            llm_reasoning=result.get("reasoning", ""),
            suggested_fix=result.get("suggested_fix", ""),
        ))
        logger.info(
            "[DEV_AGENT] FP verdict: reason=%s verdict=%s — %s",
            reason_key, result.get("verdict", "?"), result.get("reasoning", "")[:120],
        )

    return reports


def fix_false_positives(
    fp_reports: list[FalsePositiveReport],
    repo_root: Path,
    llm_client: Any,
    session_state: Any,
) -> list[str]:
    """Generate and apply code fixes for confirmed false-positive reports."""
    from telegram_signal_copier.agents.developer_agent_patch import generate_patch, apply_patch

    fixed: list[str] = []
    for fp in fp_reports:
        if fp.verdict != "FALSE_POSITIVE":
            continue
        if getattr(session_state, "fixes_this_session", 0) >= MAX_FIXES_PER_SESSION:
            logger.warning("[DEV_AGENT] Session fix limit reached — skipping %s", fp.rejection_reason)
            break
        post_fix_watch = getattr(session_state, "post_fix_watch", {})
        if fp.rejection_reason in post_fix_watch:
            logger.info("[DEV_AGENT] %s already under post-fix watch — skipping", fp.rejection_reason)
            continue

        synth = FailureReport(
            category=fp.rejection_reason,
            count=fp.count,
            total_signals=fp.count,
            example_texts=fp.examples,
            rejection_reasons=[fp.rejection_reason],
            execution_errors=[],
            description=(
                f"FALSE POSITIVE: {fp.count} valid trades were incorrectly rejected "
                f"by the '{fp.rejection_reason}' rule.\n"
                f"LLM assessment: {fp.llm_reasoning}\n"
                f"Suggested fix: {fp.suggested_fix}"
            ),
        )
        patch = generate_patch(synth, repo_root, llm_client)
        if patch is None:
            logger.warning("[DEV_AGENT] No patch generated for FP: %s", fp.rejection_reason)
            continue

        ok = apply_patch(patch, repo_root)
        if ok:
            session_state.fixes_this_session = getattr(session_state, "fixes_this_session", 0) + 1
            if hasattr(session_state, "post_fix_watch"):
                session_state.post_fix_watch[fp.rejection_reason] = time.time()
            fixed.append(fp.rejection_reason)
            logger.info("[DEV_AGENT] Fixed false-positive rule: %s", fp.rejection_reason)
        else:
            logger.warning("[DEV_AGENT] Patch apply failed for FP: %s", fp.rejection_reason)

    return fixed
