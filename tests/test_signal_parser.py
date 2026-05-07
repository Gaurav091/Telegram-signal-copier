import tempfile
import unittest
from pathlib import Path

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage
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


class SignalParserTests(unittest.TestCase):
    def test_heuristic_parser_extracts_gold_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            parser = SignalParser(config=build_config(tmp_path), ai_client=None)
            result = parser.parse(
                TelegramSignalMessage(
                    source_group="VIP Gold",
                    message_id="1",
                    raw_text="BUY GOLD NOW @ 2320 SL 2315 TP1 2330 TP2 2338",
                )
            )

            self.assertEqual(result.signal.symbol, "XAUUSD")
            self.assertEqual(result.signal.side, "BUY")
            self.assertEqual(result.signal.entry_price, 2320.0)
            self.assertEqual(result.signal.stop_loss, 2315.0)
            self.assertEqual(result.signal.take_profits, [2330.0, 2338.0])
            self.assertGreaterEqual(result.signal.confidence, 0.85)


if __name__ == "__main__":
    unittest.main()