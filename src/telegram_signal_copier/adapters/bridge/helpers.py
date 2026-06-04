"""Bridge I/O utility functions.

Static helpers extracted from FileBridgeExecutor in bridge.py to keep
each module under 300 lines.
"""
from __future__ import annotations

import logging
from pathlib import Path

from telegram_signal_copier.models import ExecutionResult, TradeCommand

logger = logging.getLogger(__name__)


def bridge_append_queue_entry(queue_path: Path, request_id: str) -> None:
    try:
        with queue_path.open("a", encoding="mbcs") as handle:
            handle.write(f"{request_id}\n")
        return
    except Exception:
        logger.debug("Queue append (mbcs) failed, retrying utf-8", exc_info=True)

    try:
        with queue_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{request_id}\n")
    except Exception:
        logger.debug("Queue append (utf-8) also failed; command files are the fallback", exc_info=True)


def bridge_write_command_file(command_path: Path, text: str) -> None:
    tmp_path = command_path.with_suffix(command_path.suffix + ".tmp")
    try:
        tmp_path.write_text(text, encoding="mbcs")
        tmp_path.replace(command_path)
    except Exception:
        try:
            tmp_path.write_text(text, encoding="utf-8")
            tmp_path.replace(command_path)
        except Exception:
            command_path.write_text(text, encoding="utf-8")


def bridge_payload_text(payload: dict[str, str]) -> str:
    return "\n".join(f"{k}={v}" for k, v in payload.items()) + "\n"


def bridge_strip_symbol_suffix(symbol: str) -> str:
    value = symbol.strip()
    upper = value.upper()
    # List of suffixes to strip, from longest to shortest to prevent partial matches
    suffixes = (
        ".MICRO", "-MICRO", "MICRO",
        ".CENT", "-CENT", "CENT",
        ".ECN", "-ECN", "ECN",
        ".PRO", "-PRO", "PRO",
        ".STD", "-STD", "STD",
        ".M", "-M", "M",
        ".C", "-C", "C",
        ".I", "-I", "I",
        "++", "+", "#", "."
    )
    for suffix in suffixes:
        if upper.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def bridge_should_retry_symbol_selection(result: ExecutionResult) -> bool:
    if result.status != "ERROR":
        return False
    msg = (result.message or "").lower()
    return ("select symbol" in msg) or ("symbol" in msg and "not found" in msg)


def bridge_normalize_execution_result(command: TradeCommand, result: ExecutionResult) -> ExecutionResult:
    """Coerce ambiguous bridge outcomes into safer statuses.

    Some EA builds return status=FILLED for pending orders as soon as order placement
    succeeds, even when no deal is filled yet. In that case executed_price is absent.
    Treat this as PENDING so downstream logs and monitoring do not report false fills.
    """
    pending_entry_types = {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}
    if (
        result.status == "FILLED"
        and str(command.action or "").upper() in {"BUY", "SELL"}
        and str(command.order_type or "").upper() in pending_entry_types
        and result.executed_price is None
    ):
        ticket_note = f" ticket={result.ticket}" if result.ticket else ""
        return ExecutionResult(
            request_id=result.request_id,
            status="PENDING",
            message=(
                "Pending order accepted by MT5; awaiting market trigger"
                f"{ticket_note}"
            ),
            ticket=result.ticket,
            executed_price=result.executed_price,
            executed_at=result.executed_at,
        )
    return result


def bridge_symbol_retry_candidates(symbol: str, symbol_suffix: str) -> list[str]:
    if not symbol:
        return []

    base = bridge_strip_symbol_suffix(symbol).upper()
    aliases: dict[str, list[str]] = {
        "NAS100": ["NAS100", "USTEC", "NQ100", "US100"],
        "US30": ["US30", "DJ30", "WS30"],
        "DJ30": ["DJ30", "US30", "WS30"],
        "SPX500": ["SPX500", "US500", "SP500"],
    }
    base_candidates = aliases.get(base, [base])
    if base not in base_candidates:
        base_candidates = [base, *base_candidates]

    suffixes = [""]
    configured_suffix = str(symbol_suffix or "").strip()
    if configured_suffix:
        suffixes.append(configured_suffix)
    
    # Common suffixes to try in order (covering standard, cent, pro, ecn, micro, etc.)
    common_suffixes = (
        "m", ".m", "-m",
        "c", ".c", "-c",
        "ecn", ".ecn", "-ecn",
        "pro", ".pro", "-pro",
        "micro", ".micro", "-micro",
        "cent", ".cent", "-cent",
        "std", ".std", "-std",
        "i", ".i", "-i",
        "j", ".j", "-j",
        "+", "++", "#", "."
    )
    for suffix in common_suffixes:
        if suffix not in suffixes:
            suffixes.append(suffix)

    seen: set[str] = set()
    candidates: list[str] = []
    for base_symbol in base_candidates:
        for suf in suffixes:
            candidate = f"{base_symbol}{suf}" if suf else base_symbol
            key = candidate.upper()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates
