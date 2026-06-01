"""Patch generation, validation, and application for the Developer Agent.

Extracted from developer_agent.py for maintainability.
"""
from __future__ import annotations

import json
import logging
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from telegram_signal_copier.agents.developer.models import (
    FailureReport,
    Patch,
    MAX_FIXES_PER_SESSION,
    _ALLOWED_PREFIX,
    _BLOCKED_FILES,
    _CATEGORY_FILES,
    _session_fix_counts,
)

logger = logging.getLogger(__name__)


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
{{"file_path": "src/telegram_signal_copier/agents/extraction_agent.py", "old_code": "<exact verbatim code block to replace — must match file exactly>", "new_code": "<replacement code block>", "explanation": "one sentence: what changed and why"}}

Respond with ONLY the JSON object. No markdown fences. No preamble."""


def _call_llm(client: Any, prompt: str) -> str:
    """Call OpenAIClient with the developer prompt."""
    messages = [
        {"role": "system", "content": "You are an expert Python developer. Respond only with valid JSON."},
        {"role": "user", "content": prompt},
    ]
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
    if not patch.file_path.startswith(_ALLOWED_PREFIX):
        logger.error("[DEV_AGENT] Patch targets disallowed path: %s", patch.file_path)
        return False

    file_name = Path(patch.file_path).name
    if file_name in _BLOCKED_FILES:
        logger.error("[DEV_AGENT] Patch targets protected file: %s", file_name)
        return False

    abs_path = repo_root / patch.file_path
    if not abs_path.exists():
        logger.error("[DEV_AGENT] Patch file does not exist: %s", abs_path)
        return False

    try:
        compile(patch.new_code, patch.file_path, "exec")
    except SyntaxError as exc:
        logger.error("[DEV_AGENT] new_code has syntax error: %s", exc)
        return False

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


def generate_patch(
    failure: FailureReport,
    repo_root: Path,
    llm_client: Any,
) -> Patch | None:
    """Ask the LLM to propose a minimal code fix for the given failure."""
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

    _git_commit_backup(repo_root, patch.file_path, f"[dev-agent] backup before fix: {patch.explanation[:80]}")

    new_content = original.replace(patch.old_code, patch.new_code, 1)

    try:
        compile(new_content, patch.file_path, "exec")
    except SyntaxError as exc:
        logger.error("[DEV_AGENT] Patched file has syntax error: %s", exc)
        return False

    abs_path.write_text(new_content, encoding="utf-8")
    _session_fix_counts[patch.file_path] = _session_fix_counts.get(patch.file_path, 0) + 1

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
        subprocess.run(
            ["git", "checkout", sha, "--", file_path],
            cwd=str(repo_root), check=True,
        )
        logger.info("[DEV_AGENT] Rolled back %s to commit %s", file_path, sha)
        return True
    except Exception as exc:
        logger.error("[DEV_AGENT] Rollback failed: %s", exc)
        return False
