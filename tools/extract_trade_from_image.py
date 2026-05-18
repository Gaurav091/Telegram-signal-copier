#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage, TradeCommand
from telegram_signal_copier.services.image_processor import ImageProcessor
from telegram_signal_copier.services.risk_engine import RiskEngine
from telegram_signal_copier.services.signal_parser import SignalParser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract trading signal fields from chart image(s) using local OCR + heuristic parser.",
    )
    parser.add_argument(
        "--image",
        action="append",
        required=True,
        help="Path to an image file. Repeat for multiple images.",
    )
    parser.add_argument(
        "--caption",
        default="",
        help="Optional caption text from Telegram message.",
    )
    parser.add_argument(
        "--source-group",
        default="LOCAL_IMAGE_UTILITY",
        help="Source group label to attach to generated signal.",
    )
    parser.add_argument(
        "--message-id",
        default=f"img-{int(datetime.now(tz=UTC).timestamp())}",
        help="Message id to attach to generated signal.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="If set and signal is approved, submit a .cmd to MT5 bridge.",
    )
    parser.add_argument(
        "--wait-result",
        action="store_true",
        help="When submitting, wait for .result from MT5 bridge.",
    )
    parser.add_argument(
        "--volume",
        type=float,
        default=None,
        help="Optional volume override. Defaults to DEFAULT_VOLUME from config.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory that contains .env and src/.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    image_paths = [Path(p).expanduser().resolve() for p in args.image]
    missing = [str(p) for p in image_paths if not p.exists()]
    if missing:
        print(json.dumps({"error": "Missing image file(s)", "paths": missing}, indent=2))
        return 2

    project_root = Path(args.project_root).expanduser().resolve()
    config = AppConfig.from_env(project_root=project_root)
    config.ensure_runtime_dirs()

    primary = str(image_paths[0])
    rest = [str(p) for p in image_paths[1:]]

    image_processor = ImageProcessor(ai_client=None)
    image_result = image_processor.extract_signal_context(
        image_path=primary,
        existing_text=args.caption,
        all_image_paths=rest,
    )

    message = TelegramSignalMessage(
        source_group=args.source_group,
        message_id=args.message_id,
        raw_text=args.caption,
        image_path=primary,
        all_image_paths=rest,
    )

    parser = SignalParser(config=config, ai_client=None)
    parse_result = parser.parse(message, image_text=image_result.extracted_text)
    parse_result.signal.notes.extend(image_result.notes)

    risk_engine = RiskEngine(config=config)
    decision = risk_engine.evaluate(parse_result.signal)

    output: dict[str, object] = {
        "mode": "local_ocr_only",
        "images": [str(p) for p in image_paths],
        "caption": args.caption,
        "ocr_text": image_result.extracted_text,
        "ocr_notes": image_result.notes,
        "parsed_signal": dataclasses.asdict(parse_result.signal),
        "decision": {
            "status": decision.status,
            "reasons": decision.reasons,
        },
    }

    if args.submit:
        if decision.approved:
            volume = args.volume if args.volume is not None else config.default_volume
            command = TradeCommand.from_signal(parse_result.signal, volume=volume)
            executor = FileBridgeExecutor(
                inbox_dir=config.bridge_inbox_dir,
                outbox_dir=config.bridge_outbox_dir,
                timeout_seconds=config.mt5_bridge_timeout_seconds,
                symbol_suffix=config.mt5_symbol_suffix,
            )
            execution_result = executor.submit(command, wait_for_result=args.wait_result)
            output["bridge_command"] = command.to_bridge_payload()
            output["execution_result"] = dataclasses.asdict(execution_result)
        else:
            output["submission_skipped"] = "Signal not approved by risk engine"

    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
