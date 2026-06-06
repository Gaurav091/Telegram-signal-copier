"""Telegram Signal Copier — entry point.

Heavy implementation is split across focused submodules:
  listener_lock.py    — lock/PID file helpers
  listener_status.py  — bridge status file writers
  listener_builder.py — build_pipeline factory
  listener_runner.py  — async runner (_run_with_restarts, _run_listener)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from contextlib import suppress
from pathlib import Path
from logging.handlers import RotatingFileHandler

from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.adapters.telegram_client import TelegramSignalListener
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.listener_builder import build_pipeline
from telegram_signal_copier.listener_lock import (
    _acquire_listener_lock,
    _clear_listener_pid,
    _listener_lock_path,
    _listener_pid_path,
    _read_pid_value,
    _release_listener_lock,
    _write_listener_pid,
)
from telegram_signal_copier.listener_runner import _run_with_restarts
from telegram_signal_copier.listener_status import (
    _bridge_root_path,
    _safe_write_text,
    _write_bridge_status,
    _write_source_map,
)
from telegram_signal_copier.models import TelegramSignalMessage
from telegram_signal_copier.services.image_processor import ImageProcessor

logger = logging.getLogger(__name__)


def configure_logging(config: AppConfig) -> None:
    logs_dir = config.project_root / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.debug("configure_logging: could not create logs dir", exc_info=True)
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


def _startup_health_check(config: AppConfig) -> None:
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

    try:
        health_path = _bridge_root_path(config) / "startup_health.txt"
        _safe_write_text(health_path, json.dumps(summary, indent=2) + "\n")
        logger.info("Wrote startup health to %s", health_path)
    except Exception:
        logger.exception("Failed to write startup health file")


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
    subparsers.add_parser("setup", help="Launch the first-run setup wizard")
    subparsers.add_parser("dashboard", help="Launch the desktop Flet GUI dashboard")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.command == "setup":
        from telegram_signal_copier.setup_wizard import run_wizard
        run_wizard()
        return

    if args.command == "dashboard":
        import flet as ft
        from telegram_signal_copier.gui import main as gui_main
        ft.run(gui_main, view=ft.AppView.FLET_APP)
        return

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

    _startup_health_check(config)
    _outer_logger = logging.getLogger("telegram_signal_copier.outer")
    _outer_attempt = 0
    if not _acquire_listener_lock(config):
        existing_pid = _read_pid_value(_listener_lock_path(config)) or _read_pid_value(_listener_pid_path(config))
        message = f"Listener already running with PID {existing_pid}" if existing_pid else "Listener already running"
        _outer_logger.warning(message)
        raise SystemExit(0)
    _write_listener_pid(config)
    try:
        while True:
            _outer_attempt += 1
            try:
                asyncio.run(_run_with_restarts(config))
                break
            except (KeyboardInterrupt, SystemExit) as _esc:
                if isinstance(_esc, SystemExit) and _esc.code not in (0, None):
                    _outer_logger.warning(
                        "SystemExit(%s) escaped asyncio.run (background task crash), "
                        "restarting event loop (outer attempt %d)",
                        _esc.code, _outer_attempt,
                    )
                    time.sleep(2)
                    continue
                raise
    finally:
        _clear_listener_pid(config)
        _release_listener_lock()


if __name__ == "__main__":
    main()
