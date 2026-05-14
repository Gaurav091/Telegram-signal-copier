#!/usr/bin/env python3
from datetime import datetime, timezone
from pathlib import Path

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage, TradeCommand, ExecutionResult
from telegram_signal_copier.services.pipeline import CopierPipeline
from telegram_signal_copier.services.signal_parser import SignalParser
from telegram_signal_copier.services.image_processor import ImageProcessor
from telegram_signal_copier.services.risk_engine import RiskEngine
from telegram_signal_copier.adapters.bridge import FileBridgeExecutor


class SimulatedExecutor(FileBridgeExecutor):
    def submit(self, command: TradeCommand, wait_for_result: bool = True, timeout_seconds: float | None = None) -> ExecutionResult:
        super().submit(command, wait_for_result=False)
        out = self.outbox_dir
        out.mkdir(parents=True, exist_ok=True)
        lines = [
            f"request_id={command.request_id}",
            "status=EXECUTED",
            "message=Simulated demo execution",
            "ticket=SIM-DEM-IMG",
            f"executed_price={command.entry_price or ''}",
            f"executed_at={datetime.now(timezone.utc).isoformat()}",
        ]
        out_path = out / f"{command.request_id}.result"
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return ExecutionResult.from_bridge_lines(lines)


def main():
    cfg = AppConfig.from_env()
    cfg.ensure_runtime_dirs()
    ai_client = None
    if cfg.ai_ready:
        from telegram_signal_copier.adapters.openai_client import OpenAIClient

        ai_client = OpenAIClient(cfg)
    pipeline = CopierPipeline(
        config=cfg,
        image_processor=ImageProcessor(ai_client=ai_client),
        signal_parser=SignalParser(config=cfg, ai_client=ai_client),
        risk_engine=RiskEngine(config=cfg),
        executor=SimulatedExecutor(cfg.bridge_inbox_dir, cfg.bridge_outbox_dir, timeout_seconds=cfg.mt5_bridge_timeout_seconds),
    )

    img_path = Path('tools/sample_signal.png')
    if not img_path.exists():
        print('Sample image missing:', img_path)
        return

    m = TelegramSignalMessage(source_group='DemoGroup', message_id='demo-image-eurusd', raw_text='', image_path=str(img_path))
    print('Processing image sample')
    outcome = pipeline.process_message(m)
    print(outcome.to_dict())


if __name__ == '__main__':
    main()
