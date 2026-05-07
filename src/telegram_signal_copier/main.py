from __future__ import annotations

import argparse
import asyncio
import json
import time
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.adapters.telegram_client import TelegramSignalListener
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage, TradeCommand
from telegram_signal_copier.services.image_processor import ImageProcessor
from telegram_signal_copier.services.pipeline import CopierPipeline
from telegram_signal_copier.services.risk_engine import RiskEngine
from telegram_signal_copier.services.signal_parser import SignalParser


def _status_file_content(status: dict[str, object]) -> str:
    lines: list[str] = []
    for key, value in status.items():
        if value is None:
            normalized = ""
        elif isinstance(value, list):
            normalized = "|".join(str(item) for item in value)
        else:
            normalized = str(value)
        normalized = " ".join(normalized.splitlines())
        lines.append(f"{key}={normalized}")
    return "\n".join(lines) + "\n"


def _safe_write_text(path: Path, content: str, attempts: int = 5, delay_seconds: float = 0.1) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    for attempt in range(attempts):
        try:
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(path)
            return
        except PermissionError:
            with suppress(FileNotFoundError):
                temp_path.unlink()
            if attempt == attempts - 1:
                return
            time.sleep(delay_seconds)


def _write_bridge_status(config: AppConfig, status: dict[str, object]) -> None:
    now = datetime.now(tz=UTC)
    payload = {
        "listener_state": status.get("listener_state", "unknown"),
        "telegram_connected": status.get("telegram_connected", "0"),
        "session_name": status.get("session_name", config.telegram_session_name),
        "identity": status.get("identity", config.telegram_username or ""),
        "source_count": status.get("source_count", len(config.telegram_source_mappings)),
        "heartbeat_epoch": int(now.timestamp()),
        "heartbeat_display": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_source_group": status.get("last_source_group", ""),
        "last_message_id": status.get("last_message_id", ""),
        "last_decision": status.get("last_decision", ""),
        "last_execution_status": status.get("last_execution_status", ""),
        "last_symbol": status.get("last_symbol", ""),
        "last_side": status.get("last_side", ""),
        "last_order_type": status.get("last_order_type", ""),
        "last_entry_price": status.get("last_entry_price", ""),
        "last_stop_loss": status.get("last_stop_loss", ""),
        "last_take_profits": status.get("last_take_profits", []),
        "last_confidence": status.get("last_confidence", ""),
        "last_trade_comment": status.get("last_trade_comment", ""),
        "last_error": status.get("last_error", ""),
    }
    status_path = config.bridge_inbox_dir.parent / "telegram_status.txt"
    _safe_write_text(status_path, _status_file_content(payload))


def _write_source_map(config: AppConfig) -> None:
    lines = [f"{index}. {label} -> {identifier}" for index, (label, identifier) in enumerate(config.telegram_source_mappings, start=1)]
    if not lines:
        lines = ["No Telegram sources configured"]
    source_map_path = config.bridge_inbox_dir.parent / "telegram_sources.txt"
    _safe_write_text(source_map_path, "\n".join(lines) + "\n")


async def _run_status_heartbeat(config: AppConfig, status: dict[str, object]) -> None:
    interval = max(1.0, min(config.poll_interval_seconds, 5.0))
    while True:
        with suppress(Exception):
            _write_bridge_status(config, status)
        await asyncio.sleep(interval)


def build_pipeline(config: AppConfig) -> CopierPipeline:
    ai_client = None
    if config.ai_ready:
        ai_client = OpenAIClient(config)
    return CopierPipeline(
        config=config,
        image_processor=ImageProcessor(ai_client=ai_client),
        signal_parser=SignalParser(config=config, ai_client=ai_client),
        risk_engine=RiskEngine(config=config),
        executor=FileBridgeExecutor(config.bridge_inbox_dir, config.bridge_outbox_dir),
    )


async def _run_listener(config: AppConfig) -> None:
    pipeline = build_pipeline(config)
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
            outcome = pipeline.process_message(message)
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
            print(json.dumps(outcome.to_dict(), indent=2))
        except Exception as exc:
            print(f"Unhandled exception in message handler: {exc}", flush=True)
            status.update({"last_error": str(exc)})

    try:
        status["listener_state"] = "running"
        await listener.run(on_message)
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


async def _run_login(config: AppConfig) -> None:
    listener = TelegramSignalListener(config)
    await listener.login()
    print(json.dumps({"status": "CONNECTED", "session_name": config.telegram_session_name}, indent=2))


def _run_sample(config: AppConfig, group: str, message_id: str, text: str, image_path: str | None) -> None:
    pipeline = build_pipeline(config)
    outcome = pipeline.process_message(
        TelegramSignalMessage(
            source_group=group,
            message_id=message_id,
            raw_text=text,
            image_path=image_path,
        )
    )
    print(json.dumps(outcome.to_dict(), indent=2))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telegram Signal Copier service")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample_parser = subparsers.add_parser("sample", help="Process one sample signal locally")
    sample_parser.add_argument("--group", default="Sample Group")
    sample_parser.add_argument("--message-id", default="local-1")
    sample_parser.add_argument("--text", required=True)
    sample_parser.add_argument("--image-path")

    subparsers.add_parser("login", help="Log in to Telegram and create a session file")
    subparsers.add_parser("listen", help="Listen to configured Telegram sources")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    config = AppConfig.from_env()
    config.ensure_runtime_dirs()
    _write_source_map(config)

    if args.command == "sample":
        _run_sample(config, args.group, args.message_id, args.text, args.image_path)
        return

    if args.command == "login":
        asyncio.run(_run_login(config))
        return

    asyncio.run(_run_listener(config))


if __name__ == "__main__":
    main()