from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler


from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.adapters.telegram_client import TelegramSignalListener
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage, TradeCommand
from telegram_signal_copier.services.cluster_agent import MessageClusterAgent
from telegram_signal_copier.services.image_processor import ImageProcessor
from telegram_signal_copier.services.pipeline import CopierPipeline
from telegram_signal_copier.services.pipeline_logger import PipelineLogger
from telegram_signal_copier.services.risk_engine import RiskEngine
from telegram_signal_copier.services.signal_parser import SignalParser


_LISTENER_LOCK_HANDLE = None


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
            try:
                path.write_text(content, encoding="utf-8")
                with suppress(FileNotFoundError):
                    temp_path.unlink()
                return
            except PermissionError:
                pass
            with suppress(FileNotFoundError):
                temp_path.unlink()
            if attempt == attempts - 1:
                return
            time.sleep(delay_seconds)


def _bridge_root_path(config: AppConfig) -> Path:
    bridge_root = config.bridge_inbox_dir
    try:
        if bridge_root.name.lower() == "inbox":
            return bridge_root.parent
    except Exception:
        pass
    return bridge_root


def _listener_pid_path(config: AppConfig) -> Path:
    return config.project_root / "runtime" / "listener.pid"


def _listener_lock_path(config: AppConfig) -> Path:
    return config.project_root / "runtime" / "listener.lock"


def _read_pid_value(path: Path) -> int | None:
    try:
        raw_value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except Exception:
        return None
    return int(raw_value) if raw_value.isdigit() else None


def _acquire_listener_lock(config: AppConfig) -> bool:
    global _LISTENER_LOCK_HANDLE

    if _LISTENER_LOCK_HANDLE is not None:
        return True

    lock_path = _listener_lock_path(config)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if lock_path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                handle.close()
                return False
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                return False

        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n".encode("utf-8"))
        handle.flush()
        _LISTENER_LOCK_HANDLE = handle
        return True
    except Exception:
        handle.close()
        raise


def _release_listener_lock() -> None:
    global _LISTENER_LOCK_HANDLE

    handle = _LISTENER_LOCK_HANDLE
    _LISTENER_LOCK_HANDLE = None
    if handle is None:
        return

    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    finally:
        with suppress(Exception):
            handle.close()


def _write_listener_pid(config: AppConfig) -> None:
    pid_path = _listener_pid_path(config)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    _safe_write_text(pid_path, f"{os.getpid()}\n")


def _clear_listener_pid(config: AppConfig) -> None:
    with suppress(FileNotFoundError):
        _listener_pid_path(config).unlink()


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
    status_path = _bridge_root_path(config) / "telegram_status.txt"
    _safe_write_text(status_path, _status_file_content(payload))


def _write_source_map(config: AppConfig) -> None:
    lines = [f"{index}. {label} -> {identifier}" for index, (label, identifier) in enumerate(config.telegram_source_mappings, start=1)]
    if not lines:
        lines = ["No Telegram sources configured"]
    source_map_path = _bridge_root_path(config) / "telegram_sources.txt"
    _safe_write_text(source_map_path, "\n".join(lines) + "\n")


def configure_logging(config: AppConfig) -> None:
    logs_dir = config.project_root / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    log_file = logs_dir / "telegram_signal_copier.log"
    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
        try:
            fh = RotatingFileHandler(str(log_file), maxBytes=5 * 1024 * 1024, backupCount=3)
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except Exception:
            root.exception("Failed to create file log handler")


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
    pipeline_log = PipelineLogger(logs_dir=config.project_root / "logs")
    return CopierPipeline(
        config=config,
        image_processor=ImageProcessor(ai_client=ai_client),
        signal_parser=SignalParser(config=config, ai_client=ai_client),
        risk_engine=RiskEngine(config=config),
        executor=FileBridgeExecutor(
            config.bridge_inbox_dir,
            config.bridge_outbox_dir,
            timeout_seconds=config.mt5_bridge_timeout_seconds,
            symbol_suffix=config.mt5_symbol_suffix,
        ),
        pipeline_logger=pipeline_log,
    )


def _startup_health_check(config: AppConfig) -> None:
    logger = logging.getLogger(__name__)
    summary: dict[str, object] = {"ai_providers": [], "ocr": {}}

    if config.ai_ready:
        try:
            ai_client = OpenAIClient(config)
            providers = ai_client.providers
            logger.info("Startup health check: AI providers configured: %d", len(providers))
            now = time.time()
            for p in providers:
                name = p.get("name") or "unnamed"
                base_url = p.get("base_url") or ""
                supports_vision = p.get("supports_vision", False)
                trip_until = p.get("trip_until", 0)
                status = "tripped" if trip_until and trip_until > now else "ok"
                # Perform a lightweight network probe when provider adapter exposes a probe method
                probe_result = None
                adapter = p.get("adapter")
                if adapter and hasattr(adapter, "probe"):
                    try:
                        probe_ok = adapter.probe()
                        probe_result = True if probe_ok else False
                    except Exception as exc:
                        probe_result = f"error: {exc}"

                logger.info("    - %s: base_url=%s vision=%s status=%s probe=%s", name, base_url, supports_vision, status, probe_result)
                summary["ai_providers"].append({"name": name, "base_url": base_url, "vision": supports_vision, "status": status, "probe": probe_result})
        except Exception as exc:
            logger.exception("AI client init failed: %s", exc)
            summary["ai_error"] = str(exc)
    else:
        logger.info("Startup health check: No AI providers configured")

    # OCR availability
    try:
        img_proc = ImageProcessor(ai_client=None)
        ocr_ok = getattr(img_proc, "_ocr_available", False)
        if ocr_ok:
            try:
                ver = img_proc._pytesseract.get_tesseract_version()
                logger.info("Local OCR: python packages present, tesseract available: %s", ver)
                summary["ocr"] = {"python_packages": True, "tesseract": str(ver)}
            except Exception:
                logger.info("Local OCR: python packages present, tesseract binary NOT found or inaccessible")
                summary["ocr"] = {"python_packages": True, "tesseract": False}
        else:
            logger.info("Local OCR: pytesseract/Pillow not installed")
            summary["ocr"] = {"python_packages": False, "tesseract": False}
    except Exception as exc:
        logger.exception("Local OCR check failed: %s", exc)
        summary["ocr"] = {"error": str(exc)}

    # Write startup health summary to bridge folder
    try:
        health_path = _bridge_root_path(config) / "startup_health.txt"
        _safe_write_text(health_path, json.dumps(summary, indent=2) + "\n")
        logger.info("Wrote startup health to %s", health_path)
    except Exception:
        logger.exception("Failed to write startup health file")


async def _run_with_restarts(config: AppConfig) -> None:
    import traceback as _tb
    _restart_logger = logging.getLogger("telegram_signal_copier.restarts")
    attempt = 0

    def _restart_backoff_seconds(attempt_number: int) -> int:
        # Recover quickly from transient Telegram/network drops instead of
        # leaving the listener offline for several minutes.
        return(min(30, 2 ** min(attempt_number, 5)))

    while True:
        attempt += 1
        try:
            _restart_logger.info("Starting listener (attempt %d)", attempt)
            print(f"Starting listener (attempt {attempt})", flush=True)
            await _run_listener(config)
            # run_until_disconnected returned normally → connection dropped; treat as crash and restart
            _restart_logger.warning("Listener exited unexpectedly (run_until_disconnected returned) — restarting")
            print("Listener exited unexpectedly — restarting", flush=True)
            backoff = _restart_backoff_seconds(attempt)
            await asyncio.sleep(backoff)
            continue
        except BaseException as exc:
            tb = _tb.format_exc()
            _restart_logger.error("Listener crashed (attempt %d): %s\n%s", attempt, exc, tb)
            print(f"Listener crashed: {type(exc).__name__}: {exc}", flush=True)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            # exponential backoff with cap
            backoff = _restart_backoff_seconds(attempt)
            _restart_logger.info("Restarting listener in %ds (attempt %d)", backoff, attempt)
            print(f"Restarting listener in {backoff}s (attempt {attempt})", flush=True)
            await asyncio.sleep(backoff)


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
            # pipeline.process_message is synchronous and makes blocking I/O
            # calls (OpenAI API, tesseract OCR). Running it in the default
            # thread-pool executor keeps the asyncio event loop free to
            # service Telethon's IOCP callbacks and prevents WinError 121
            # (semaphore timeout) caused by blocking the ProactorEventLoop.
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
            print(json.dumps(outcome.to_dict(), indent=2))
        except Exception as exc:
            print(f"Unhandled exception in message handler: {exc}", flush=True)
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
    configure_logging(config)
    _write_source_map(config)

    if args.command == "sample":
        _run_sample(config, args.group, args.message_id, args.text, args.image_path)
        return

    if args.command == "login":
        asyncio.run(_run_login(config))
        return

    # Run a startup health check and then start listener with automatic restarts
    _startup_health_check(config)
    # In Python 3.9+, asyncio.Task.__step() re-raises SystemExit and
    # KeyboardInterrupt from background tasks directly through the event-loop,
    # bypassing any try/except in the main coroutine (_run_with_restarts).
    # A Telethon background task can raise SystemExit(1) (e.g. via cryptg or
    # a network-error path) and the whole process would exit silently.
    # The outer restart loop below catches those SystemExit(1) escapes and
    # restarts by calling asyncio.run() again with a fresh event loop.
    _outer_logger = logging.getLogger("telegram_signal_copier.outer")
    _outer_attempt = 0
    if not _acquire_listener_lock(config):
        existing_pid = _read_pid_value(_listener_lock_path(config)) or _read_pid_value(_listener_pid_path(config))
        message = f"Listener already running with PID {existing_pid}" if existing_pid else "Listener already running"
        _outer_logger.warning(message)
        print(message, flush=True)
        raise SystemExit(0)
    _write_listener_pid(config)
    try:
        while True:
            _outer_attempt += 1
            try:
                asyncio.run(_run_with_restarts(config))
                break  # clean exit (should never reach here under normal operation)
            except (KeyboardInterrupt, SystemExit) as _esc:
                if isinstance(_esc, SystemExit) and _esc.code not in (0, None):
                    # Non-zero SystemExit — almost certainly from a background task
                    # crash (e.g. Telethon's crypto or IOCP path).  Restart.
                    _outer_logger.warning(
                        "SystemExit(%s) escaped asyncio.run (background task crash), "
                        "restarting event loop (outer attempt %d)",
                        _esc.code, _outer_attempt,
                    )
                    time.sleep(2)
                    continue
                # code 0 / None = clean exit, or KeyboardInterrupt — propagate
                raise
    finally:
        _clear_listener_pid(config)
        _release_listener_lock()


if __name__ == "__main__":
    main()