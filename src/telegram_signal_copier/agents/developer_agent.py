"""Developer Agent — analyses systematic pipeline failures and generates code fixes.

Called by the smart supervisor when it detects a recurring failure pattern.

Safety guarantees
-----------------
* Only modifies files under ``src/telegram_signal_copier/``
* Never touches ``.env``, ``config.py`` secrets, test files, or binary files
* Always creates a git commit *before* applying the patch (easy rollback)
* Generated patch is syntax-checked (``compile()``) before being written to disk
* ``old_code`` must match exactly once in the target file
* At most ``MAX_FIXES_PER_SESSION`` fixes applied per process lifetime

Returned JSON schema from LLM
------------------------------
{
  "file_path": "src/telegram_signal_copier/agents/extraction_agent.py",
  "old_code":  "<exact verbatim block to replace>",
  "new_code":  "<replacement block>",
  "explanation": "one-sentence explanation of what changed and why"
}
"""
from __future__ import annotations

import json
import logging
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

MAX_FIXES_PER_SESSION = 10
_ALLOWED_PREFIX = "src/telegram_signal_copier/"
_BLOCKED_FILES = {
    "config.py",
    "schemas.py",      # shared data contracts — changing would break everything
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

    category: str           # e.g. "INTENT_UNKNOWN", "MISSING_SL", "LOW_RR", "PARSE_FAIL"
    count: int              # how many times in the sample window
    total_signals: int      # total signals in the sample
    example_texts: list[str]      # raw signal text that failed (up to 5)
    rejection_reasons: list[str]  # from pipeline logs
    execution_errors: list[str]   # from pipeline logs
    description: str        # human-readable summary for the LLM prompt


@dataclass
class Patch:
    """A proposed code change."""

    file_path: str   # relative to repo root, e.g. "src/.../extraction_agent.py"
    old_code: str
    new_code: str
    explanation: str


@dataclass
class FalsePositiveReport:
    """Result of evaluating whether a rejection rule is over-strict."""

    rejection_reason: str      # e.g. "INVALID_PRICE_RANGE"
    verdict: str               # "FALSE_POSITIVE" | "CORRECT_REJECTION" | "UNCERTAIN"
    count: int                 # how many signals rejected for this reason
    examples: list[str]        # signal text snippets
    llm_reasoning: str         # LLM explanation
    suggested_fix: str         # LLM suggestion (empty if CORRECT_REJECTION)


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

# Map failure category → list of relevant source files (relative to repo root)
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


def classify_failures(recent_logs: list[dict[str, Any]], window: int = 50) -> FailureReport | None:
    """Scan the last ``window`` pipeline log entries and return the dominant failure.

    Returns ``None`` if there are no actionable patterns (healthy or too few samples).
    """
    if not recent_logs:
        return None

    sample = recent_logs[-window:]
    total = len(sample)

    # Only trade signals matter (skip INFORMATIONAL / TRADE_UPDATE)
    signals = [e for e in sample if e.get("intent") in ("NEW_SIGNAL", "UNKNOWN", None)]
    if not signals:
        return None

    rejected = [e for e in signals if e.get("action_taken") == "REJECTED"]
    failed_execution = [
        e for e in signals
        if e.get("action_taken") == "OPEN_TRADE"
        and e.get("execution_status") not in ("FILLED", "SUBMITTED", "DRY_RUN")
    ]

    # Count rejection reason categories
    from collections import Counter
    reason_counter: Counter[str] = Counter()
    for e in rejected:
        for r in (e.get("rejection_reasons") or []):
            reason_counter[r] += 1

    # Count intent unknowns
    unknown_count = sum(1 for e in signals if e.get("intent") in ("UNKNOWN", None) and not e.get("extraction"))

    # Count extraction failures: intent=NEW_SIGNAL but extraction agent produced no symbol.
    # Exclude entries that have explicit rejection_reasons — those reached validation fine.
    extract_fail = sum(
        1 for e in signals
        if e.get("intent") == "NEW_SIGNAL"
        and not (e.get("extraction") or {}).get("symbol_raw")
        and not e.get("rejection_reasons")  # has reasons → made it past extraction
    )

    # Decide dominant failure
    failure_threshold = max(2, total // 4)  # at least 25% of sample OR 2+

    # Check each category in priority order
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
        category = "BRIDGE_TIMEOUT" if any("timeout" in (e or "").lower() for e in errors) else "EXECUTION_ERROR"
        return FailureReport(
            category=category,
            count=len(failed_execution),
            total_signals=total,
            example_texts=examples,
            rejection_reasons=[],
            execution_errors=errors[:5],
            description=f"{len(failed_execution)}/{total} signals approved but execution failed: {errors[:3]}",
        )

    return None  # healthy


def _get_examples(entries: list[dict], predicate) -> list[str]:
    texts = [
        e.get("text_snippet") or e.get("raw_text_snippet") or ""
        for e in entries
        if predicate(e) and (e.get("text_snippet") or e.get("raw_text_snippet"))
    ]
    return texts[:5]


# ---------------------------------------------------------------------------
# Developer Agent — patch generation
# ---------------------------------------------------------------------------


def generate_patch(
    failure: FailureReport,
    repo_root: Path,
    llm_client: Any,  # OpenAIClient instance
) -> Patch | None:
    """Ask the LLM to propose a minimal code fix for the given failure.

    Returns a ``Patch`` if the LLM returns a valid, applicable patch,
    else ``None``.
    """
    total_fixed = sum(_session_fix_counts.values())
    if total_fixed >= MAX_FIXES_PER_SESSION:
        logger.warning("[DEV_AGENT] Session fix limit (%d) reached — pausing fixes", MAX_FIXES_PER_SESSION)
        return None

    source_files = _load_relevant_sources(failure.category, repo_root)
    if not source_files:
        logger.warning("[DEV_AGENT] No relevant source files for category=%s", failure.category)
        return None

    prompt = _build_prompt(failure, source_files)

    logger.info("[DEV_AGENT] Requesting fix for category=%s from LLM", failure.category)
    try:
        response = _call_llm(llm_client, prompt)
    except Exception as exc:
        logger.error("[DEV_AGENT] LLM call failed: %s", exc)
        return None

    patch = _parse_patch_response(response)
    if patch is None:
        logger.warning("[DEV_AGENT] LLM returned unparseable response")
        return None

    if not _validate_patch(patch, repo_root):
        return None

    return patch


def apply_patch(patch: Patch, repo_root: Path) -> bool:
    """Apply the patch to disk.  Creates a git commit first for easy rollback."""
    abs_path = repo_root / patch.file_path
    if not abs_path.exists():
        logger.error("[DEV_AGENT] Cannot apply patch — file not found: %s", abs_path)
        return False

    original = abs_path.read_text(encoding="utf-8")
    if original.count(patch.old_code) != 1:
        count = original.count(patch.old_code)
        logger.error("[DEV_AGENT] old_code appears %d times in %s (need exactly 1)", count, patch.file_path)
        return False

    # Git commit original state for rollback
    _git_commit_backup(repo_root, patch.file_path, f"[dev-agent] backup before fix: {patch.explanation[:80]}")

    new_content = original.replace(patch.old_code, patch.new_code, 1)

    # Final syntax check on the whole file
    try:
        compile(new_content, patch.file_path, "exec")
    except SyntaxError as exc:
        logger.error("[DEV_AGENT] Patched file has syntax error: %s", exc)
        return False

    abs_path.write_text(new_content, encoding="utf-8")
    _session_fix_counts[patch.file_path] = _session_fix_counts.get(patch.file_path, 0) + 1

    # Commit the fix
    _git_commit_backup(repo_root, patch.file_path, f"[dev-agent] fix: {patch.explanation[:80]}")

    logger.info("[DEV_AGENT] Patch applied to %s — %s", patch.file_path, patch.explanation)
    return True


def rollback_last_patch(repo_root: Path, file_path: str) -> bool:
    """Revert the last git commit that touched file_path."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5", "--", file_path],
            cwd=str(repo_root), capture_output=True, text=True,
        )
        lines = result.stdout.strip().splitlines()
        backup_commits = [l for l in lines if "[dev-agent] backup" in l]
        if not backup_commits:
            logger.warning("[DEV_AGENT] No backup commit found for %s", file_path)
            return False
        sha = backup_commits[0].split()[0]
        # Restore file to that commit's version
        subprocess.run(
            ["git", "checkout", sha, "--", file_path],
            cwd=str(repo_root), check=True,
        )
        logger.info("[DEV_AGENT] Rolled back %s to commit %s", file_path, sha)
        return True
    except Exception as exc:
        logger.error("[DEV_AGENT] Rollback failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# False-positive rejection analysis
# ---------------------------------------------------------------------------


def assess_false_positives(
    rejected_entries: list[dict],
    repo_root: Path,
    llm_client: Any,
    min_count: int = 2,
) -> list["FalsePositiveReport"]:
    """Examine rejected pipeline log entries and determine if any validation
    rules are over-strict (i.e. blocking valid trades).

    For each rejection category with *min_count* or more occurrences, the LLM
    evaluates the rejected examples against the validation code and returns:

    * ``FALSE_POSITIVE``     — rule is too strict; these trades should have passed
    * ``CORRECT_REJECTION``  — rule correctly blocked a bad/risky signal
    * ``UNCERTAIN``          — not enough information to decide
    """
    if not rejected_entries:
        return []

    from collections import defaultdict
    by_reason: dict[str, list[dict]] = defaultdict(list)
    for entry in rejected_entries:
        reasons = entry.get("rejection_reasons") or []
        for r in reasons:
            key = r.split(":")[0].replace("RejectionReason.", "").strip().upper()
            by_reason[key].append(entry)
            break  # only primary reason per entry

    reports: list[FalsePositiveReport] = []
    for reason_key, entries in by_reason.items():
        if len(entries) < min_count:
            continue

        examples = [
            (e.get("text_snippet") or e.get("raw_text_snippet") or "")[:250]
            for e in entries[:6]
            if (e.get("text_snippet") or e.get("raw_text_snippet"))
        ]

        source_files = _load_relevant_sources(reason_key, repo_root)
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

        logger.info(
            "[DEV_AGENT] Assessing FP for rejection reason=%s (%d examples)", reason_key, len(entries)
        )
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
    fp_reports: list["FalsePositiveReport"],
    repo_root: Path,
    llm_client: Any,
    session_state: Any,
) -> list[str]:
    """Generate and apply code fixes for confirmed false-positive reports.

    Returns list of rejection-reason categories that were successfully fixed.
    """
    import time as _time

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
                session_state.post_fix_watch[fp.rejection_reason] = _time.time()
            fixed.append(fp.rejection_reason)
            logger.info("[DEV_AGENT] Fixed false-positive rule: %s", fp.rejection_reason)
        else:
            logger.warning("[DEV_AGENT] Patch apply failed for FP: %s", fp.rejection_reason)

    return fixed


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
{{
  "verdict": "FALSE_POSITIVE",
  "reasoning": "One or two sentence explanation",
  "suggested_fix": "Concrete description of what threshold/condition to change"
}}

OR:
{{
  "verdict": "CORRECT_REJECTION",
  "reasoning": "Why the rejection is valid",
  "suggested_fix": ""
}}

OR:
{{
  "verdict": "UNCERTAIN",
  "reasoning": "Why it is unclear",
  "suggested_fix": ""
}}

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_relevant_sources(category: str, repo_root: Path) -> dict[str, str]:
    rel_paths = _CATEGORY_FILES.get(category, [])
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


def _build_prompt(failure: FailureReport, source_files: dict[str, str]) -> str:
    examples_block = "\n".join(
        f"  [{i+1}] {textwrap.shorten(t, 200)}" for i, t in enumerate(failure.example_texts)
    ) or "  (no example texts available)"

    sources_block = "\n\n".join(
        f"=== FILE: {path} ===\n{code}" for path, code in source_files.items()
    )

    return f"""You are an expert Python developer tasked with fixing a bug in a Telegram signal copier system.

## FAILURE REPORT
Category: {failure.category}
Occurrences: {failure.count} out of {failure.total_signals} signals
Description: {failure.description}

Rejection reasons seen: {failure.rejection_reasons}
Execution errors seen: {failure.execution_errors}

## EXAMPLE FAILED SIGNAL TEXTS
{examples_block}

## RELEVANT SOURCE CODE
{sources_block}

## YOUR TASK
Propose a MINIMAL code fix that addresses this failure pattern.
- Fix only what is broken — do not refactor or rewrite
- The fix must be syntactically correct Python
- Keep the same function signatures and module structure
- Do NOT modify imports unless absolutely necessary

## RESPONSE FORMAT (JSON only, no markdown, no explanation outside the JSON)
{{
  "file_path": "src/telegram_signal_copier/agents/extraction_agent.py",
  "old_code": "<exact verbatim code block to replace — must match file exactly>",
  "new_code": "<replacement code block>",
  "explanation": "one sentence: what changed and why"
}}

Respond with ONLY the JSON object. No markdown fences. No preamble."""


def _call_llm(client: Any, prompt: str) -> str:
    """Call OpenAIClient with the developer prompt."""
    messages = [
        {"role": "system", "content": "You are an expert Python developer. Respond only with valid JSON."},
        {"role": "user", "content": prompt},
    ]
    # OpenAIClient._call_with_fallbacks returns a dict with 'choices'
    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }
    resp = client._call_with_fallbacks("/chat/completions", payload, "developer_agent")
    return resp["choices"][0]["message"]["content"]


def _parse_patch_response(response: str) -> Patch | None:
    """Parse LLM JSON response into a Patch object."""
    try:
        # Strip markdown fences if present
        text = response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("[DEV_AGENT] Failed to parse LLM response as JSON: %s\nResponse: %s", exc, response[:500])
        return None

    for field in ("file_path", "old_code", "new_code", "explanation"):
        if not data.get(field):
            logger.error("[DEV_AGENT] LLM response missing field '%s'", field)
            return None

    return Patch(
        file_path=data["file_path"],
        old_code=data["old_code"],
        new_code=data["new_code"],
        explanation=data["explanation"],
    )


def _validate_patch(patch: Patch, repo_root: Path) -> bool:
    """Check patch is safe to apply."""
    # Must be within allowed prefix
    if not patch.file_path.startswith(_ALLOWED_PREFIX):
        logger.error("[DEV_AGENT] Patch targets disallowed path: %s", patch.file_path)
        return False

    # Must not be a blocked file
    file_name = Path(patch.file_path).name
    if file_name in _BLOCKED_FILES:
        logger.error("[DEV_AGENT] Patch targets protected file: %s", file_name)
        return False

    # File must exist
    abs_path = repo_root / patch.file_path
    if not abs_path.exists():
        logger.error("[DEV_AGENT] Patch file does not exist: %s", abs_path)
        return False

    # new_code must be syntactically valid Python
    try:
        compile(patch.new_code, patch.file_path, "exec")
    except SyntaxError as exc:
        logger.error("[DEV_AGENT] new_code has syntax error: %s", exc)
        return False

    # old_code must appear exactly once
    original = abs_path.read_text(encoding="utf-8")
    count = original.count(patch.old_code)
    if count != 1:
        logger.error("[DEV_AGENT] old_code appears %d times in %s (need exactly 1)", count, patch.file_path)
        return False

    return True


def _git_commit_backup(repo_root: Path, file_path: str, message: str) -> None:
    try:
        subprocess.run(["git", "add", file_path], cwd=str(repo_root), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", message, "--allow-empty"],
            cwd=str(repo_root), check=True, capture_output=True,
        )
    except Exception as exc:
        logger.warning("[DEV_AGENT] Git commit failed (non-fatal): %s", exc)
