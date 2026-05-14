"""Tests for intent filter, vision handling, and image-type classification.

Run:
    .venv\\Scripts\\python.exe tools/test_agents_images.py
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
import tempfile
import warnings
from unittest.mock import MagicMock, patch

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
warnings.filterwarnings("ignore", category=UserWarning)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
MEDIA_DIR = pathlib.Path("runtime/media")

os.environ["AGENT_MIN_RR"] = "1.5"


def section(title: str) -> None:
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def ok(msg: str) -> None:
    print(f"  {PASS}  {msg}")


def fail(msg: str) -> None:
    print(f"  {FAIL}  {msg}")


failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        ok(msg)
    else:
        fail(msg)
        failures.append(msg)


# ---------------------------------------------------------------------------
# Build shared infra
# ---------------------------------------------------------------------------

from telegram_signal_copier.models import ExecutionResult
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.agents.graph import build_graph, run_on_message
import telegram_signal_copier.agents.validation_agent as _va

td_path = pathlib.Path(tempfile.mkdtemp())
config = AppConfig(
    project_root=td_path,
    bridge_inbox_dir=td_path / "inbox",
    bridge_outbox_dir=td_path / "outbox",
    telegram_api_id=None, telegram_api_hash=None,
    telegram_phone_number=None, telegram_session_name="test",
    telegram_sources=[], openai_api_key="sk-fake",
    openai_model="gpt-4o-mini", openai_base_url="https://api.openai.com/v1",
    minimum_confidence=0.0, default_volume=0.01,
    allowed_symbols=["XAUUSD", "ETHUSD", "BTCUSD", "EURUSD"],
    dry_run=False, approval_required_below=0.5, poll_interval_seconds=1.0,
)

mock_llm = MagicMock()
mock_executor = MagicMock()
mock_executor.submit.return_value = ExecutionResult(
    request_id="img-id", status="FILLED", message="OK", ticket="77001"
)

graph = build_graph(config, mock_llm, mock_executor)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def set_intent_response(intent: str, confidence: float = 0.95) -> None:
    """Make mock LLM return intent JSON for the intent_filter node."""
    mock_llm.invoke.return_value = MagicMock(content=json.dumps({
        "intent": intent, "confidence": confidence, "reason": "test"
    }))


def set_extraction_response(payload: dict) -> None:
    mock_llm.invoke.return_value = MagicMock(content=json.dumps(payload))


def set_sequence(*responses: dict) -> None:
    """Queue multiple LLM responses in order."""
    side_effects = [MagicMock(content=json.dumps(r)) for r in responses]
    mock_llm.invoke.side_effect = side_effects


# ===========================================================================
# TEST 10 — Intent filter: "TP HIT" text → TRADE_UPDATE skip (keyword, no LLM)
# ===========================================================================
section("TEST 10 — Intent filter: TP HIT keyword → skip without LLM call")

mock_llm.invoke.side_effect = None
mock_llm.invoke.reset_mock()

_va._SEEN_FINGERPRINTS.clear()
r10 = run_on_message(graph, "TP 1 HIT 50 PIPS PROFIT DONE", "TEST", "msg_010")

check(r10.execution_status is None, "No execution on TP-hit message")
check(r10.intent == "TRADE_UPDATE", f"Intent=TRADE_UPDATE (got {r10.intent})")
# Keyword path should not call the LLM at all
check(mock_llm.invoke.call_count == 0, f"LLM not called for keyword match (calls={mock_llm.invoke.call_count})")


# ===========================================================================
# TEST 11 — Intent filter: "Buy Gold" keyword → NEW_SIGNAL, no LLM intent call
# ===========================================================================
section("TEST 11 — Intent filter: Buy keyword → NEW_SIGNAL shortcut")

mock_llm.invoke.reset_mock()
mock_llm.invoke.side_effect = None
_va._SEEN_FINGERPRINTS.clear()

# extraction LLM returns Gold BUY signal
mock_llm.invoke.return_value = MagicMock(content=json.dumps({
    "symbol_raw": "Gold", "side": "BUY", "order_type": "MARKET",
    "entry_price": 4750.0, "stop_loss": 4740.0,
    "take_profits": [4775.0], "confidence": 0.9, "notes": [],
}))

r11 = run_on_message(graph, "Buy Gold at 4750, SL 4740, TP 4775", "TEST", "msg_011")

check(r11.intent == "NEW_SIGNAL", f"Intent=NEW_SIGNAL (got {r11.intent})")
check(r11.execution_status == "FILLED", f"Executed (got {r11.execution_status})")
# Intent was determined by keyword → only 1 LLM call (extraction, not intent)
check(mock_llm.invoke.call_count == 1, f"Only extraction LLM call (calls={mock_llm.invoke.call_count})")


# ===========================================================================
# TEST 12 — Intent filter: LLM classifies MT5 screenshot as TRADE_UPDATE
# ===========================================================================
section("TEST 12 — Intent filter: MT5 trade screenshot → TRADE_UPDATE (LLM)")

mock_llm.invoke.reset_mock()
mock_llm.invoke.side_effect = None
_va._SEEN_FINGERPRINTS.clear()

# intent_filter LLM response = TRADE_UPDATE with high confidence
mock_llm.invoke.return_value = MagicMock(content=json.dumps({
    "intent": "TRADE_UPDATE", "confidence": 0.95, "reason": "MT5 open position screenshot"
}))

# Simulate sending the MT5 trade confirmation screenshot (11617.jpg = XAUUSD buy card)
img = str(MEDIA_DIR / "11617.jpg") if (MEDIA_DIR / "11617.jpg").exists() else None
r12 = run_on_message(graph, "", "TEST", "msg_012", image_path=img)

check(r12.intent == "TRADE_UPDATE", f"Intent=TRADE_UPDATE (got {r12.intent})")
check(r12.execution_status is None, "No execution on trade update")
# image-only: LLM IS called for intent classification (no keyword shortcut)
check(mock_llm.invoke.call_count == 1, f"Intent LLM call made (calls={mock_llm.invoke.call_count})")


# ===========================================================================
# TEST 13 — Intent filter: promo banner → INFORMATIONAL skip
# ===========================================================================
section("TEST 13 — Intent filter: promo banner → INFORMATIONAL skip")

mock_llm.invoke.reset_mock()
mock_llm.invoke.side_effect = None
_va._SEEN_FINGERPRINTS.clear()

mock_llm.invoke.return_value = MagicMock(content=json.dumps({
    "intent": "INFORMATIONAL", "confidence": 0.97, "reason": "Broker promo/logo image"
}))

img_promo = str(MEDIA_DIR / "5618.jpg") if (MEDIA_DIR / "5618.jpg").exists() else None
r13 = run_on_message(graph, "Personal Trading Room SALE!", "TEST", "msg_013", image_path=img_promo)

check(r13.intent == "INFORMATIONAL", f"Intent=INFORMATIONAL (got {r13.intent})")
check(r13.execution_status is None, "No execution on promo message")


# ===========================================================================
# TEST 14 — Image-only chart: no caption → goes to extraction, not rejected
# ===========================================================================
section("TEST 14 — Image-only TradingView chart (no caption) → extraction attempted")

mock_llm.invoke.reset_mock()
mock_llm.invoke.side_effect = None
_va._SEEN_FINGERPRINTS.clear()

# intent_filter: image-only shortcut → returns NEW_SIGNAL without LLM
# Then extraction LLM returns parsed chart levels
# Image-only with no caption → intent LLM classifies it, then extraction LLM parses it
# Call 1: intent_filter LLM → NEW_SIGNAL
# Call 2: extraction LLM → chart levels
mock_llm.invoke.side_effect = [
    MagicMock(content=json.dumps({"intent": "NEW_SIGNAL", "confidence": 0.9, "reason": "TradingView chart with TP/SL zones"})),
    MagicMock(content=json.dumps({
        "symbol_raw": "XAUUSD", "side": "BUY", "order_type": "MARKET",
        "entry_price": 4741.0, "stop_loss": 4733.0,
        "take_profits": [4761.0], "confidence": 0.75,
        "notes": ["entry from chart current price", "TP from green zone top", "SL from red zone bottom"],
    })),
]

chart_img = str(MEDIA_DIR / "7885.jpg") if (MEDIA_DIR / "7885.jpg").exists() else None
r14 = run_on_message(graph, "", "TEST", "msg_014", image_path=chart_img)

check(r14.intent == "NEW_SIGNAL", f"Intent=NEW_SIGNAL for image-only (got {r14.intent})")
check(r14.extracted_signal is not None, "Extraction attempted")
check(r14.extracted_signal and r14.extracted_signal.symbol_raw == "XAUUSD",
      f"Symbol extracted from chart header (got {r14.extracted_signal.symbol_raw if r14.extracted_signal else None})")
# image-only now calls LLM twice (intent + extraction)
check(mock_llm.invoke.call_count == 2, f"Intent+extraction LLM calls (calls={mock_llm.invoke.call_count})")


# ===========================================================================
# TEST 15 — "BUY GOLD NEAR 4703-4701 SL:-4699" range entry format
# ===========================================================================
section("TEST 15 — Range entry 'NEAR 4703-4701 SL:-4699' correctly parsed")

mock_llm.invoke.reset_mock()
mock_llm.invoke.side_effect = None
_va._SEEN_FINGERPRINTS.clear()

mock_executor.submit.return_value = ExecutionResult(
    request_id="range-id", status="FILLED", message="OK", ticket="55001"
)

# LLM correctly parses range entry as midpoint / BUY_LIMIT
mock_llm.invoke.return_value = MagicMock(content=json.dumps({
    "symbol_raw": "Gold", "side": "BUY", "order_type": "BUY_LIMIT",
    "entry_price": 4702.0,   # midpoint of 4703-4701
    "stop_loss": 4699.0,
    "take_profits": [4720.0],
    "confidence": 0.85,
    "notes": ["entry is midpoint of range 4703-4701"],
}))

r15 = run_on_message(
    graph, "BUY GOLD NEAR 4703-4701 SL :- 4699 TP 4720", "TEST", "msg_015"
)

check(r15.execution_status == "FILLED", f"Executed range-entry signal (got {r15.execution_status})")
check(
    r15.validated_signal is not None and r15.validated_signal.order_type.value == "BUY_LIMIT",
    f"Order type BUY_LIMIT (got {r15.validated_signal.order_type if r15.validated_signal else None})"
)
check(
    r15.validated_signal is not None and r15.validated_signal.entry_price == 4702.0,
    f"Entry = midpoint 4702.0 (got {r15.validated_signal.entry_price if r15.validated_signal else None})"
)


# ===========================================================================
# TEST 16 — Multiple images (multi-chart signal)
# ===========================================================================
section("TEST 16 — Multi-image signal: all images sent to extraction LLM")

mock_llm.invoke.reset_mock()
mock_llm.invoke.side_effect = None
_va._SEEN_FINGERPRINTS.clear()

img1 = str(MEDIA_DIR / "7885.jpg") if (MEDIA_DIR / "7885.jpg").exists() else None
img2 = str(MEDIA_DIR / "9146.jpg") if (MEDIA_DIR / "9146.jpg").exists() else None

# intent_filter LLM call (call 1) returns intent response
# extraction LLM (call 2) returns chart levels 
mock_llm.invoke.side_effect = [
    MagicMock(content=json.dumps({"intent": "NEW_SIGNAL", "confidence": 0.85, "reason": "multi-TF chart signal"})),
    MagicMock(content=json.dumps({
        "symbol_raw": "XAUUSD", "side": "BUY", "order_type": "MARKET",
        "entry_price": 4741.0, "stop_loss": 4730.0,
        "take_profits": [4761.0, 4780.0], "confidence": 0.82,
        "notes": ["multi-timeframe confirmation"],
    })),
]

r16 = run_on_message(
    graph, "Multi-TF analysis — go long Gold",
    "TEST", "msg_016",
    image_path=img1,
    image_paths=[img2] if img2 else [],
)

check(r16.intent == "NEW_SIGNAL", f"NEW_SIGNAL for multi-image (got {r16.intent})")
check(r16.extracted_signal is not None, "Extraction OK")
check(mock_llm.invoke.call_count >= 1, "LLM called for extraction")


# ===========================================================================
# TEST 17 — Ambiguous LLM intent → defaults to extraction (safe)
# ===========================================================================
section("TEST 17 — Ambiguous intent (low confidence) → proceed to extraction")

mock_llm.invoke.reset_mock()
mock_llm.invoke.side_effect = None
_va._SEEN_FINGERPRINTS.clear()

# First call = intent with low confidence INFORMATIONAL (below threshold)
# Second call = extraction
responses = [
    {"intent": "INFORMATIONAL", "confidence": 0.65, "reason": "unclear"},
    {
        "symbol_raw": "EURUSD", "side": "SELL", "order_type": "MARKET",
        "entry_price": 1.0800, "stop_loss": 1.0820,
        "take_profits": [1.0750], "confidence": 0.8, "notes": [],
    },
]
mock_llm.invoke.side_effect = [MagicMock(content=json.dumps(r)) for r in responses]
mock_executor.submit.return_value = ExecutionResult(
    request_id="amb-id", status="FILLED", message="OK", ticket="33001"
)

r17 = run_on_message(graph, "Some market analysis on EURUSD", "TEST", "msg_017")

# Low confidence INFORMATIONAL (0.65 < 0.88) → should proceed to extract
check(r17.execution_status == "FILLED", f"Low-conf INFORMATIONAL not skipped (got {r17.execution_status})")


# ===========================================================================
# SUMMARY
# ===========================================================================
section("SUMMARY")
if failures:
    for f_ in failures:
        print(f"  FAILED: {f_}")
    print(f"\n  {len(failures)} test(s) failed.")
    sys.exit(1)
else:
    print(f"  All 8 image/intent tests PASSED.")
