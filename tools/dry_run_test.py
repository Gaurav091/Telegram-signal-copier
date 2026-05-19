"""Dry-run pipeline tester (section 14 of AGENT_SPEC.md).

Feeds pre-recorded messages through the full LangGraph agent pipeline and
prints what action WOULD have been taken, without writing any .cmd files.

Usage
-----
    # Run all built-in sample cases
    & ".venv/Scripts/python.exe" tools/dry_run_test.py

    # Supply your own test-case JSON file
    & ".venv/Scripts/python.exe" tools/dry_run_test.py --input tests/sample_messages.json

    # Verbose mode (shows full extracted signal details)
    & ".venv/Scripts/python.exe" tools/dry_run_test.py --verbose

    # Override model for this run only
    & ".venv/Scripts/python.exe" tools/dry_run_test.py --model gpt-4o-mini

The tool forces DRY_RUN=true so the execution agent logs the trade details
but never touches the file bridge.

Test-case JSON format
---------------------
[
  {
    "test_id":           "T001",
    "description":       "Simple text signal",
    "messages": [
      {"text": "EURUSD BUY NOW\\nSL: 1.0800\\nTP1: 1.0920", "has_image": false}
    ],
    "expected_intent":   "NEW_SIGNAL",
    "expected_action":   "OPEN_TRADE",
    "expected_symbol":   "EURUSD",
    "expected_direction": "buy"
  }
]

If ``expected_*`` keys are present the tool checks results against them and
marks each test PASS / FAIL.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add project src to path so the tool can be run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from langchain_openai import ChatOpenAI

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.agents.graph import build_graph, run_on_message
from telegram_signal_copier.agents.schemas import AgentState
from telegram_signal_copier.config import AppConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dry_run_test")

# ---------------------------------------------------------------------------
# Built-in sample test cases (mirrors AGENT_SPEC section 14)
# ---------------------------------------------------------------------------

BUILT_IN_CASES: list[dict] = [
    {
        "test_id": "T001",
        "description": "Simple text signal",
        "messages": [
            {
                "text": "EURUSD BUY NOW\nSL: 1.0800\nTP1: 1.0920\nTP2: 1.0980",
                "has_image": False,
            }
        ],
        "expected_intent": "NEW_SIGNAL",
        "expected_action": "OPEN_TRADE",
        "expected_symbol": "EURUSD",
        "expected_direction": "buy",
    },
    {
        "test_id": "T002",
        "description": "TP hit with breakeven instruction",
        "messages": [
            {
                "text": "🎉 TP1 HIT on EURUSD BUY! Move SL to breakeven!",
                "has_image": False,
            }
        ],
        "expected_intent": "TRADE_UPDATE",
        "expected_action": "IGNORE",
    },
    {
        "test_id": "T003",
        "description": "Pure market commentary — no action",
        "messages": [
            {
                "text": "DXY showing weakness this week, EUR may strengthen",
                "has_image": False,
            }
        ],
        "expected_intent": "INFORMATIONAL",
        "expected_action": "IGNORE",
    },
    {
        "test_id": "T004",
        "description": "Gold buy signal",
        "messages": [
            {
                "text": "GOLD BUY @ 2310\nSL: 2290\nTP: 2370",
                "has_image": False,
            }
        ],
        "expected_intent": "NEW_SIGNAL",
        "expected_action": "OPEN_TRADE",
        "expected_symbol": "XAUUSD",
        "expected_direction": "buy",
    },
    {
        "test_id": "T005",
        "description": "GBPJPY sell signal with multiple TPs",
        "messages": [
            {
                "text": "SELL GBPJPY 193.50\nSL 194.20\nTP1 192.00\nTP2 191.00",
                "has_image": False,
            }
        ],
        "expected_intent": "NEW_SIGNAL",
        "expected_action": "OPEN_TRADE",
        "expected_symbol": "GBPJPY",
        "expected_direction": "sell",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_action(state: AgentState) -> str:
    """Map final AgentState to a simplified action label."""
    if state.execution_status in ("FILLED", "SUBMITTED", "DRY_RUN"):
        return "OPEN_TRADE"
    if state.intent in ("TRADE_UPDATE", "INFORMATIONAL"):
        return "IGNORE"
    if state.execution_status in ("REJECTED", "ERROR") or state.rejection_reasons:
        return "REJECTED"
    return "IGNORE"


def _check_expectations(case: dict, state: AgentState, action: str) -> tuple[bool, list[str]]:
    failures: list[str] = []

    expected_intent = case.get("expected_intent", "").upper()
    if expected_intent:
        actual_intent = (state.intent or "").upper()
        if actual_intent != expected_intent:
            failures.append(
                f"intent: expected={expected_intent!r} actual={actual_intent!r}"
            )

    expected_action = case.get("expected_action", "").upper()
    if expected_action:
        if action.upper() != expected_action:
            failures.append(
                f"action: expected={expected_action!r} actual={action.upper()!r}"
            )

    expected_symbol = case.get("expected_symbol", "").upper()
    if expected_symbol and state.validated_signal:
        actual_sym = (state.validated_signal.symbol or "").upper()
        if actual_sym != expected_symbol:
            failures.append(
                f"symbol: expected={expected_symbol!r} actual={actual_sym!r}"
            )

    expected_direction = case.get("expected_direction", "").lower()
    if expected_direction and state.validated_signal:
        actual_dir = str(state.validated_signal.side or "").lower()
        if actual_dir != expected_direction:
            failures.append(
                f"direction: expected={expected_direction!r} actual={actual_dir!r}"
            )

    return (len(failures) == 0, failures)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run pipeline tester")
    parser.add_argument(
        "--input",
        metavar="FILE",
        help="Path to JSON file with test cases (default: built-in cases)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override LLM model for this run (e.g. gpt-4o-mini)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print full state dicts")
    args = parser.parse_args()

    # Force dry-run so nothing hits the file bridge
    os.environ["DRY_RUN"] = "true"

    config = AppConfig.from_env(_REPO_ROOT)
    config = type(config)(**{**config.__dict__, "dry_run": True})

    model = args.model or os.getenv("AGENT_OPENAI_MODEL") or config.openai_model or "gpt-4o-mini"
    api_key = config.openai_api_key or os.getenv("OPENAI_API_KEY") or "no-key"
    base_url = os.getenv("AGENT_OPENAI_BASE_URL") or config.openai_base_url

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        max_tokens=512,
    )

    executor = FileBridgeExecutor(
        inbox_dir=config.bridge_inbox_dir,
        outbox_dir=config.bridge_outbox_dir,
        symbol_suffix=config.mt5_symbol_suffix,
    )

    graph = build_graph(config, llm, executor)

    # Load test cases
    if args.input:
        cases = json.loads(Path(args.input).read_text(encoding="utf-8"))
        logger.info("Loaded %d test cases from %s", len(cases), args.input)
    else:
        cases = BUILT_IN_CASES
        logger.info("Using %d built-in test cases", len(cases))

    # ── Run cases ─────────────────────────────────────────────────────────
    results: list[dict] = []
    passed = 0
    failed = 0

    for case in cases:
        test_id = case.get("test_id", "?")
        description = case.get("description", "")

        # Build combined text from all messages in the case
        texts = [m.get("text", "") for m in case.get("messages", []) if m.get("text")]
        combined_text = "\n".join(texts)

        print(f"\n{'─' * 60}")
        print(f"[{test_id}] {description}")
        print(f"  Input: {combined_text[:120]!r}")

        state = run_on_message(
            compiled_graph=graph,
            raw_text=combined_text,
            source_group=f"dry_run/{test_id}",
            message_id=test_id,
        )

        action = _resolve_action(state)
        ok, failures = _check_expectations(case, state, action)

        print(f"  Intent:    {state.intent} (conf={state.intent_confidence:.2f})")
        if state.validated_signal:
            v = state.validated_signal
            print(
                f"  Signal:    {v.symbol} {v.side.value if v.side else '?'} "
                f"entry={v.entry_price} sl={v.stop_loss} tp={v.take_profits}"
            )
        if state.rejection_reasons:
            print(f"  Rejected:  {state.rejection_reasons}")
        print(f"  Action:    {action}")
        print(f"  Result:    {'PASS ✓' if ok else 'FAIL ✗'}")
        if failures:
            for f_msg in failures:
                print(f"    ✗ {f_msg}")

        if args.verbose:
            print("  Full state:")
            print(
                json.dumps(
                    state.model_dump(exclude_none=True, mode="json"),
                    indent=4,
                )
            )

        if ok:
            passed += 1
        else:
            failed += 1

        results.append(
            {
                "test_id": test_id,
                "description": description,
                "passed": ok,
                "failures": failures,
                "intent": state.intent,
                "action": action,
            }
        )

    # ── Summary ───────────────────────────────────────────────────────────
    total = passed + failed
    print(f"\n{'═' * 60}")
    print(f"RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f" — {failed} FAILED")
    else:
        print(" — ALL PASSED ✓")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
