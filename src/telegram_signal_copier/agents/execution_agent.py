"""MT5 Execution Agent.

Translates a ``ValidatedSignal`` into a ``TradeCommand``, writes it to the
FileBridge inbox, and waits for the MT5 EA result file.

The agent logs the order ticket on success and surfaces the EA's error
message on failure without raising — routing control stays with LangGraph.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.agents.schemas import AgentState
from telegram_signal_copier.models import ExecutionResult, TradeCommand
from telegram_signal_copier.config import AppConfig

logger = logging.getLogger(__name__)


def _build_trade_command(state: AgentState, volume: float) -> TradeCommand:
    """Convert a ValidatedSignal into the TradeCommand the bridge understands."""
    v = state.validated_signal
    assert v is not None  # guard — caller already checked

    return TradeCommand(
        request_id=str(uuid4()),
        source_group=v.source_group or state.source_group,
        message_id=v.message_id or state.message_id,
        symbol=v.symbol,
        action=v.side.value,               # "BUY" | "SELL"
        order_type=v.order_type.value,     # "MARKET" | "BUY_LIMIT" | ...
        volume=volume,
        entry_price=v.entry_price,
        stop_loss=v.stop_loss,
        take_profit=v.managed_take_profit,
        take_profit_targets=list(v.take_profits),
        comment=v.comment or f"TG|{state.source_group[:16]}|{state.message_id[-8:]}",
    )


def execution_agent_node(
    state: AgentState,
    executor: FileBridgeExecutor,
    app_config: AppConfig,
) -> dict[str, Any]:
    """LangGraph node: submit trade to MT5 via the file bridge."""
    if state.validated_signal is None:
        logger.error("[EXECUTE] Called without a validated signal — routing to reject")
        return {
            "execution_error": "No validated signal present",
            "execution_status": "ERROR",
            "next_node": "reject",
        }

    # Ensure volume > 0: use validated_signal.volume (always >= 0.01 by Pydantic), fallback to app_config, final fallback to 0.01
    volume: float = state.validated_signal.volume
    if volume <= 0:
        volume = float(getattr(app_config, "default_volume", 0.01) or 0.01)
    if volume <= 0:
        volume = 0.01
    
    logger.debug("[EXECUTE] Volume resolved to %.4f (from signal=%.4f, config=%s)", 
                 volume, state.validated_signal.volume, getattr(app_config, "default_volume", None))

    # Dry-run mode — log but do not actually write the command file
    if getattr(app_config, "dry_run", False):
        logger.info(
            "[EXECUTE] DRY-RUN symbol=%s side=%s entry=%s sl=%s tp=%s vol=%.2f",
            state.validated_signal.symbol,
            state.validated_signal.side,
            state.validated_signal.entry_price,
            state.validated_signal.stop_loss,
            state.validated_signal.managed_take_profit,
            volume,
        )
        return {
            "execution_status": "DRY_RUN",
            "order_ticket": "DRY_RUN",
            "next_node": "end",
        }

    try:
        command = _build_trade_command(state, volume)
    except Exception as exc:
        logger.error("[EXECUTE] Failed to build TradeCommand: %s", exc)
        return {
            "execution_error": f"TradeCommand build failed: {exc}",
            "execution_status": "ERROR",
            "next_node": "reject",
        }

    logger.info(
        "[EXECUTE] Submitting request_id=%s symbol=%s side=%s order_type=%s entry=%s sl=%s tp=%s vol=%.2f",
        command.request_id,
        command.symbol,
        command.action,
        command.order_type,
        command.entry_price,
        command.stop_loss,
        command.take_profit,
        command.volume,
    )

    try:
        result: ExecutionResult = executor.submit(command, wait_for_result=True)
    except Exception as exc:
        logger.error("[EXECUTE] Bridge submission raised: %s", exc)
        return {
            "execution_error": f"Bridge error: {exc}",
            "execution_status": "ERROR",
            "next_node": "reject",
        }

    if result.status in {"FILLED", "SUBMITTED", "PENDING"}:
        logger.info(
            "[EXECUTE] SUCCESS status=%s ticket=%s price=%s",
            result.status,
            result.ticket,
            result.executed_price,
        )
        return {
            "execution_status": result.status,
            "order_ticket": result.ticket or command.request_id,
            "next_node": "end",
        }

    # MT5 EA returned an error status
    logger.error(
        "[EXECUTE] FAILED status=%s message=%s",
        result.status,
        result.message,
    )
    return {
        "execution_error": f"MT5 status={result.status}: {result.message}",
        "execution_status": result.status,
        "next_node": "reject",
    }
