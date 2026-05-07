import tempfile
import unittest
from pathlib import Path

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage, TradeCommand
from telegram_signal_copier.services.image_processor import ImageProcessor
from telegram_signal_copier.services.pipeline import CopierPipeline
from telegram_signal_copier.services.risk_engine import RiskEngine
from telegram_signal_copier.services.signal_parser import SignalParser


def build_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        project_root=tmp_path,
        bridge_inbox_dir=tmp_path / "inbox",
        bridge_outbox_dir=tmp_path / "outbox",
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_phone_number=None,
        telegram_session_name="test-session",
        telegram_sources=[],
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        openai_base_url="https://api.openai.com/v1",
        minimum_confidence=0.70,
        default_volume=0.10,
        allowed_symbols=["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"],
        dry_run=True,
        approval_required_below=0.85,
        poll_interval_seconds=1.0,
    )


class PipelineTests(unittest.TestCase):
    def test_pipeline_dry_run_returns_execution_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            pipeline = CopierPipeline(
                config=config,
                image_processor=ImageProcessor(ai_client=None),
                signal_parser=SignalParser(config=config, ai_client=None),
                risk_engine=RiskEngine(config=config),
                executor=FileBridgeExecutor(config.bridge_inbox_dir, config.bridge_outbox_dir),
            )

            outcome = pipeline.process_message(
                TelegramSignalMessage(
                    source_group="VIP Gold",
                    message_id="2",
                    raw_text="BUY GOLD NOW @ 2320 SL 2315 TP1 2330 TP2 2338",
                )
            )

            self.assertEqual(outcome.decision.status, "APPROVED")
            self.assertIsNotNone(outcome.execution_result)
            self.assertEqual(outcome.execution_result.status, "DRY_RUN")

    def test_trade_comment_contains_group_slug_for_mt5_logs(self) -> None:
        command = TradeCommand.from_signal(
            SignalParser(config=build_config(Path(".")), ai_client=None).parse(
                TelegramSignalMessage(
                    source_group="Forex Focus",
                    message_id="17102",
                    raw_text="BUY GOLD NOW @ 2320 SL 2315 TP1 2330 TP2 2338",
                )
            ).signal,
            volume=0.10,
        )

        self.assertEqual(command.comment, "TG|FOREX-FOCUS|17102")


if __name__ == "__main__":
    unittest.main()