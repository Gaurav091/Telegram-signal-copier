"""Comprehensive end-to-end test for the multi-agent LangGraph pipeline.

Run:
    .venv\\Scripts\\python.exe tools/test_agents.py
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
import tempfile
import traceback
import warnings
from unittest.mock import MagicMock

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

# Silence LangGraph RunnableConfig UserWarnings during tests
warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def section(title: str) -> None:
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def ok(msg: str) -> None:
    print(f"  {PASS}  {msg}")


def fail(msg: str) -> None:
    print(f"  {FAIL}  {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Build shared infrastructure
# ---------------------------------------------------------------------------

from telegram_signal_copier.models import ExecutionResult
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.agents.graph import build_graph, run_on_message
from telegram_signal_copier.agents.schemas import AgentState

td_path = pathlib.Path(tempfile.mkdtemp())

config = AppConfig(
    project_root=td_path,
    bridge_inbox_dir=td_path / "inbox",
    bridge_outbox_dir=td_path / "outbox",
    telegram_api_id=None,
    telegram_api_hash=None,
    telegram_phone_number=None,
    telegram_session_name="test",
    telegram_sources=[],
    openai_api_key="sk-fake",
    openai_model="gpt-4o-mini",
    openai_base_url="https://api.openai.com/v1",
    minimum_confidence=0.0,
    default_volume=0.01,
    allowed_symbols=["XAUUSD", "EURUSD", "BTCUSD"],
    dry_run=False,
    approval_required_below=0.5,
    poll_interval_seconds=1.0,
)

# Fresh deduplication set per test run
import telegram_signal_copier.agents.validation_agent as _va
_va._SEEN_FINGERPRINTS.clear()
os.environ["AGENT_MIN_RR"] = "1.5"

mock_llm = MagicMock()
mock_executor = MagicMock()
mock_executor.submit.return_value = ExecutionResult(
    request_id="bridge-id", status="FILLED", message="Order placed", ticket="99001"
)

graph = build_graph(config, mock_llm, mock_executor)

failures: list[str] = []


def run(label: str, raw_text: str, llm_json: dict, msg_id: str) -> AgentState:
    mock_llm.invoke.return_value = MagicMock(content=json.dumps(llm_json))
    return run_on_message(graph, raw_text, source_group="TEST_CHAN", message_id=msg_id)


def check(cond: bool, msg: str) -> None:
    if cond:
        ok(msg)
    else:
        fail(msg)
        failures.append(msg)


# ===========================================================================
# TEST 1 — Happy path: Gold BUY with full parameters
# ===========================================================================
section("TEST 1 — Happy path (Gold BUY, full params)")

r1 = run(
    "T1",
    "Buy Gold at 2300, SL 2290, TP1 2320 TP2 2340",
    {
        "symbol_raw": "Gold", "side": "BUY", "order_type": "MARKET",
        "entry_price": 2300.0, "stop_loss": 2290.0,
        "take_profits": [2320.0, 2340.0], "confidence": 0.95, "notes": [],
    },
    "msg_001",
)

check(r1.extraction_error is None, "No extraction error")
check(r1.rejection_reasons == [], f"No rejection reasons — got {r1.rejection_reasons}")
check(r1.validated_signal is not None, "ValidatedSignal present")
check(r1.validated_signal.symbol == "XAUUSD", f"Symbol mapped Gold→XAUUSD (got {r1.validated_signal.symbol})")
check(r1.validated_signal.risk_reward_ratio == 2.0, f"R:R = 2.0 (got {r1.validated_signal.risk_reward_ratio})")
check(r1.execution_status == "FILLED", f"Execution FILLED (got {r1.execution_status})")
check(r1.order_ticket == "99001", f"Ticket = 99001 (got {r1.order_ticket})")


# ===========================================================================
# TEST 2 — Rejection: missing stop loss
# ===========================================================================
section("TEST 2 — Rejection: missing SL")

r2 = run(
    "T2",
    "Sell EURUSD now",
    {
        "symbol_raw": "EURUSD", "side": "SELL", "order_type": "MARKET",
        "entry_price": 1.0800, "stop_loss": None,
        "take_profits": [1.0750], "confidence": 0.6, "notes": ["no SL"],
    },
    "msg_002",
)

check(r2.execution_status is None, "No execution attempted")
check("MISSING_SL" in str(r2.rejection_reasons), f"Rejected: MISSING_SL (got {r2.rejection_reasons})")


# ===========================================================================
# TEST 3 — Rejection: R:R too low
# ===========================================================================
section("TEST 3 — Rejection: R:R below minimum (1.5)")

r3 = run(
    "T3",
    "Buy Gold at 2300 SL 2290 TP 2301",
    {
        "symbol_raw": "Gold", "side": "BUY", "order_type": "MARKET",
        "entry_price": 2300.0, "stop_loss": 2290.0,
        "take_profits": [2301.0], "confidence": 0.9, "notes": [],
    },
    "msg_003",
)

check(r3.execution_status is None, "No execution attempted")
check("INVALID_RR" in str(r3.rejection_reasons), f"Rejected: INVALID_RR (got {r3.rejection_reasons})")


# ===========================================================================
# TEST 4 — Rejection: symbol not in allowed list
# ===========================================================================
section("TEST 4 — Rejection: symbol not in allowed list")

r4 = run(
    "T4",
    "Buy GBPJPY at 190.00 SL 189.50 TP 191.00",
    {
        "symbol_raw": "GBPJPY", "side": "BUY", "order_type": "MARKET",
        "entry_price": 190.00, "stop_loss": 189.50,
        "take_profits": [191.00], "confidence": 0.9, "notes": [],
    },
    "msg_004",
)

check(r4.execution_status is None, "No execution attempted")
check("SYMBOL_NOT_ALLOWED" in str(r4.rejection_reasons), f"Rejected: SYMBOL_NOT_ALLOWED (got {r4.rejection_reasons})")


# ===========================================================================
# TEST 5 — Colloquial symbol aliases
# ===========================================================================
section("TEST 5 — Colloquial symbol aliases")

for raw_name, expected_broker in [
    ("XAU", "XAUUSD"),
    ("GOLD", "XAUUSD"),
    ("BTC", "BTCUSD"),
    ("BITCOIN", "BTCUSD"),
    ("WTI", "USOIL"),
    ("NAS100", "NAS100"),
]:
    _va._SEEN_FINGERPRINTS.clear()
    r = run(
        f"alias-{raw_name}",
        f"Buy {raw_name} SL 100 TP 200",
        {
            "symbol_raw": raw_name, "side": "BUY", "order_type": "MARKET",
            "entry_price": 150.0, "stop_loss": 100.0,
            "take_profits": [200.0], "confidence": 0.9, "notes": [],
        },
        f"alias_{raw_name}",
    )
    # Some symbols not in allow-list (USOIL, NAS100) — check mapping logic only via schema
    from telegram_signal_copier.agents.validation_agent import _canonical_symbol
    mapped = _canonical_symbol(raw_name)
    check(mapped == expected_broker, f"{raw_name} → {mapped} (expected {expected_broker})")


# ===========================================================================
# TEST 6 — LLM extraction error (malformed JSON) → graceful reject
# ===========================================================================
section("TEST 6 — Extraction error: malformed LLM response")

mock_llm.invoke.return_value = MagicMock(content="not valid JSON at all {{{")
r6 = run_on_message(graph, "some signal text", source_group="TEST_CHAN", message_id="msg_006")

check(r6.extraction_error is not None, f"Extraction error captured: {r6.extraction_error}")
check(r6.execution_status is None, "No execution attempted after bad LLM response")


# ===========================================================================
# TEST 7 — Duplicate signal deduplication
# ===========================================================================
section("TEST 7 — Duplicate signal deduplication")

_va._SEEN_FINGERPRINTS.clear()
dup_payload = {
    "symbol_raw": "Gold", "side": "BUY", "order_type": "MARKET",
    "entry_price": 2310.0, "stop_loss": 2300.0,
    "take_profits": [2330.0], "confidence": 0.9, "notes": [],
}
mock_executor.submit.return_value = ExecutionResult(
    request_id="dup-id", status="FILLED", message="OK", ticket="99999"
)
r7a = run("T7a", "Buy Gold 2310 SL 2300 TP 2330", dup_payload, "msg_007a")
check(r7a.execution_status == "FILLED", f"First signal executed (got {r7a.execution_status})")

r7b = run("T7b", "Buy Gold 2310 SL 2300 TP 2330", dup_payload, "msg_007b")
check("DUPLICATE" in str(r7b.rejection_reasons), f"Duplicate rejected (got {r7b.rejection_reasons})")


# ===========================================================================
# TEST 8 — Dry-run mode
# ===========================================================================
section("TEST 8 — Dry-run mode")

import dataclasses
dry_config = dataclasses.replace(config, dry_run=True)
dry_graph = build_graph(dry_config, mock_llm, mock_executor)
_va._SEEN_FINGERPRINTS.clear()

mock_llm.invoke.return_value = MagicMock(content=json.dumps({
    "symbol_raw": "Gold", "side": "SELL", "order_type": "MARKET",
    "entry_price": 2300.0, "stop_loss": 2310.0,
    "take_profits": [2280.0], "confidence": 0.9, "notes": [],
}))
r8 = run_on_message(dry_graph, "Sell Gold 2300 SL 2310 TP 2280", "DRYCHAN", "dry_001")

check(r8.execution_status == "DRY_RUN", f"Status=DRY_RUN (got {r8.execution_status})")
check(mock_executor.submit.call_count == 2, "Bridge submit NOT called in dry-run")  # still 2 from T7


# ===========================================================================
# TEST 9 — Limit order type preserved
# ===========================================================================
section("TEST 9 — Limit order type preserved through pipeline")

_va._SEEN_FINGERPRINTS.clear()
mock_executor.submit.return_value = ExecutionResult(
    request_id="lmt-id", status="SUBMITTED", message="Pending", ticket="88001"
)
r9 = run(
    "T9",
    "Buy Limit EURUSD @ 1.0750, SL 1.0700, TP 1.0850",
    {
        "symbol_raw": "EURUSD", "side": "BUY", "order_type": "BUY_LIMIT",
        "entry_price": 1.0750, "stop_loss": 1.0700,
        "take_profits": [1.0850], "confidence": 0.92, "notes": [],
    },
    "msg_009",
)

check(r9.execution_status == "SUBMITTED", f"Limit order submitted (got {r9.execution_status})")
check(r9.validated_signal is not None and r9.validated_signal.order_type.value == "BUY_LIMIT",
      f"Order type BUY_LIMIT preserved (got {r9.validated_signal.order_type if r9.validated_signal else None})")


# ===========================================================================
# Summary
# ===========================================================================
section("SUMMARY")
if failures:
    for f_ in failures:
        print(f"  FAILED: {f_}")
    print(f"\n  {len(failures)} test(s) failed.")
    sys.exit(1)
else:
    print(f"  All 9 test scenarios PASSED.")
