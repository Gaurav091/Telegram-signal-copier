"""Async listener runner functions.

Extracted from main.py for maintainability.
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
from contextlib import suppress

from telegram_signal_copier.adapters.telegram_client import TelegramSignalListener
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.listener.builder import build_pipeline
from telegram_signal_copier.listener.status import _write_bridge_status
from telegram_signal_copier.models import TelegramSignalMessage, TradeCommand
from telegram_signal_copier.services.cluster_agent import MessageClusterAgent

logger = logging.getLogger(__name__)


async def _run_status_heartbeat(config: AppConfig, status: dict[str, object]) -> None:
    interval = max(1.0, min(config.poll_interval_seconds, 5.0))
    while True:
        with suppress(Exception):
            _write_bridge_status(config, status)
        await asyncio.sleep(interval)


async def _run_listener(config: AppConfig) -> None:
    pipeline = build_pipeline(config)
    cluster_agent = MessageClusterAgent(
        allowed_symbols=config.merged_allowed_symbols,
    )
    listener = TelegramSignalListener(config)
    status: dict[str, object] = {
        "listener_state": "starting",
        "telegram_connected": "1",
        "session_name": config.telegram_session_name,
        "identity": config.telegram_username or config.telegram_first_name or "",
        "source_count": len(config.telegram_source_mappings),
        "last_trade_comment": "",
        "last_error": "",
    }
    heartbeat_task = asyncio.create_task(_run_status_heartbeat(config, status))

    async def on_message(message: TelegramSignalMessage) -> None:
        try:
            loop = asyncio.get_running_loop()
            outcome = await loop.run_in_executor(None, pipeline.process_message, message)
            signal = outcome.parse_result.signal
            execution_result = outcome.execution_result
            trade_comment = status.get("last_trade_comment", "")
            if outcome.decision.status == "APPROVED" and signal.symbol and signal.side:
                trade_comment = TradeCommand.from_signal(signal, volume=config.default_volume).comment
            status.update(
                {
                    "last_source_group": signal.source_group,
                    "last_message_id": signal.message_id,
                    "last_decision": outcome.decision.status,
                    "last_execution_status": execution_result.status if execution_result else "",
                    "last_symbol": signal.symbol or "",
                    "last_side": signal.side or "",
                    "last_order_type": signal.order_type,
                    "last_entry_price": signal.entry_price if signal.entry_price is not None else "",
                    "last_stop_loss": signal.stop_loss if signal.stop_loss is not None else "",
                    "last_take_profits": signal.take_profits,
                    "last_confidence": f"{signal.confidence:.2f}",
                    "last_trade_comment": trade_comment,
                    "last_error": "",
                }
            )
            logger.info("[HANDLER] outcome: %s", json.dumps(outcome.to_dict()))
        except Exception as exc:
            logger.exception("Unhandled exception in message handler: %s", exc)
            status.update({"last_error": str(exc)})

    async def on_message_clustered(message: TelegramSignalMessage) -> None:
        await cluster_agent.process(message, on_message)

    try:
        status["listener_state"] = "running"
        await listener.run(on_message_clustered)
    except Exception as exc:
        status.update(
            {
                "listener_state": "error",
                "telegram_connected": "0",
                "last_error": str(exc),
            }
        )
        with suppress(Exception):
            _write_bridge_status(config, status)
        raise
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        status.update({"listener_state": "stopped", "telegram_connected": "0"})
        with suppress(Exception):
            _write_bridge_status(config, status)


async def _run_with_restarts(config: AppConfig) -> None:
    _restart_logger = logging.getLogger("telegram_signal_copier.restarts")
    attempt = 0

    def _restart_backoff_seconds(attempt_number: int) -> int:
        return min(30, 2 ** min(attempt_number, 5))

    while True:
        attempt += 1
        try:
            _restart_logger.info("Starting listener (attempt %d)", attempt)
            await _run_listener(config)
            _restart_logger.warning("Listener exited unexpectedly (run_until_disconnected returned) — restarting")
            backoff = _restart_backoff_seconds(attempt)
            await asyncio.sleep(backoff)
            continue
        except BaseException as exc:
            tb = traceback.format_exc()
            _restart_logger.error("Listener crashed (attempt %d): %s\n%s", attempt, exc, tb)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if "AuthKeyDuplicatedError" in type(exc).__name__:
                _restart_logger.error(
                    "CRITICAL ERROR: Telegram session authentication key was invalidated (AuthKeyDuplicatedError).\n"
                    "This happens when the same session is used on two different machines/IPs simultaneously.\n"
                    "TO RESOLVE:\n"
                    "  1. Delete all '.session' files in the project root and in 'runtime/sessions/'.\n"
                    "  2. Run the login command to create a new session: python -m telegram_signal_copier login\n"
                    "  3. Restart the listener.\n"
                    "Terminating runner..."
                )
                raise SystemExit(0)
            backoff = _restart_backoff_seconds(attempt)
            _restart_logger.info("Restarting listener in %ds (attempt %d)", backoff, attempt)
            await asyncio.sleep(backoff)
