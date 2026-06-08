import tempfile
import unittest
from pathlib import Path

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage
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


class SignalParserTests(unittest.TestCase):
    def test_heuristic_parser_extracts_gold_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            parser = SignalParser(config=build_config(tmp_path), ai_client=None)
            result = parser.parse(
                TelegramSignalMessage(
                    source_group="VIP Gold",
                    message_id="1",
                    raw_text="BUY GOLD NOW @ 4320 SL 4315 TP1 4330 TP2 4338",
                )
            )

            self.assertEqual(result.signal.symbol, "XAUUSD")
            self.assertEqual(result.signal.side, "BUY")
            self.assertEqual(result.signal.entry_price, 4320.0)
            self.assertEqual(result.signal.stop_loss, 4315.0)
            self.assertEqual(result.signal.take_profits, [4330.0, 4338.0])
            self.assertGreaterEqual(result.signal.confidence, 0.85)

    def test_heuristic_parser_accepts_slash_style_sl_tp_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            parser = SignalParser(config=build_config(tmp_path), ai_client=None)
            result = parser.parse(
                TelegramSignalMessage(
                    source_group="ALGO TRADING forex.",
                    message_id="11722",
                    raw_text="XAUUSD SELL NOW: 4582 4586\nS/L: 4600\nT/P1: 4580\nT/P2: 4575\nT/P3: 4556",
                )
            )

            self.assertEqual(result.signal.symbol, "XAUUSD")
            self.assertEqual(result.signal.side, "SELL")
            self.assertEqual(result.signal.entry_range_low, 4582.0)
            self.assertEqual(result.signal.entry_range_high, 4586.0)
            self.assertEqual(result.signal.entry_price, 4584.0)
            self.assertEqual(result.signal.stop_loss, 4600.0)
            self.assertEqual(result.signal.take_profits, [4580.0, 4575.0, 4556.0])

    def test_heuristic_parser_extracts_gta_range_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            parser = SignalParser(config=build_config(tmp_path), ai_client=None)
            result = parser.parse(
                TelegramSignalMessage(
                    source_group="GTA VIP || 3.0",
                    message_id="5162",
                    raw_text="Gold buy @4511- 4502\n\nTarget- 4514, 4520, 4530\n\nSl- 4499",
                )
            )

            self.assertEqual(result.signal.symbol, "XAUUSD")
            self.assertEqual(result.signal.side, "BUY")
            self.assertEqual(result.signal.order_type, "BUY_LIMIT")
            self.assertEqual(result.signal.entry_range_low, 4502.0)
            self.assertEqual(result.signal.entry_range_high, 4511.0)
            self.assertEqual(result.signal.entry_price, 4506.5)
            self.assertEqual(result.signal.stop_loss, 4499.0)
            self.assertEqual(result.signal.take_profits, [4514.0, 4520.0, 4530.0])

    def test_mt5_screenshot_parser_overrides_bad_ai_lot_size_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            parser = SignalParser(config=config, ai_client=None)
            risk = RiskEngine(config=config)
            result = parser.parse(
                TelegramSignalMessage(
                    source_group="ALGO TRADING forex.",
                    message_id="11776",
                    raw_text="New",
                    image_path="11776.jpg",
                ),
                image_text=(
                    "XAUUSD, sell 0.50 350\n"
                    "4 499.54 - 4 499.47\n"
                    "#1338763137 Open: 2026.05.22 17:30:00\n"
                    "S/L: 4534.51 Swap: 0.00\n"
                    "T/P: 4 452.20\n"
                    "Comment: 100004"
                ),
                image_ai_payload={
                    "symbol": "XAUUSD",
                    "side": "SELL",
                    "order_type": "MARKET",
                    "entry_price": 0.5,
                    "entry_range_low": 0.5,
                    "entry_range_high": 0.5,
                    "stop_loss": 4534.51,
                    "take_profits": [4499.47, 4492.2],
                    "confidence": 1.0,
                    "notes": ["Vision providers unavailable"],
                },
            )

            self.assertTrue(result.used_ai)
            self.assertEqual(result.signal.symbol, "XAUUSD")
            self.assertEqual(result.signal.side, "SELL")
            self.assertEqual(result.signal.entry_price, 4499.54)
            self.assertEqual(result.signal.stop_loss, 4534.51)
            self.assertEqual(result.signal.take_profits, [4452.2])
            self.assertEqual(result.signal.parser_name, "openai+mt5_screenshot")
            self.assertTrue(
                any("overrode AI-extracted" in note for note in result.signal.notes),
                result.signal.notes,
            )
            self.assertTrue(risk.evaluate(result.signal).approved)

    def test_ai_payload_repairs_btc_entry_when_leading_digits_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            config.allowed_symbols.append("BTCUSD")
            parser = SignalParser(config=config, ai_client=None)

            result = parser.parse(
                TelegramSignalMessage(
                    source_group="ALGO TRADING forex.",
                    message_id="11782",
                    raw_text="New",
                    image_path="11782.jpg",
                ),
                image_text="",
                image_ai_payload={
                    "symbol": "BTCUSD",
                    "side": "BUY",
                    "order_type": "MARKET",
                    "entry_price": 645.45,
                    "stop_loss": 76764.84,
                    "take_profits": [78523.57],
                    "confidence": 1.0,
                    "notes": [],
                },
            )

            self.assertEqual(result.signal.symbol, "BTCUSD")
            self.assertEqual(result.signal.side, "BUY")
            self.assertEqual(result.signal.entry_price, 77645.45)
            self.assertEqual(result.signal.stop_loss, 76764.84)
            self.assertEqual(result.signal.take_profits, [78523.57])
            self.assertTrue(
                any("Adjusted entry" in note for note in result.signal.notes),
                result.signal.notes,
            )

    def test_ai_payload_keeps_valid_btc_entry_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            config.allowed_symbols.append("BTCUSD")
            parser = SignalParser(config=config, ai_client=None)

            result = parser.parse(
                TelegramSignalMessage(
                    source_group="ALGO TRADING forex.",
                    message_id="11783",
                    raw_text="New",
                    image_path="11783.jpg",
                ),
                image_text="",
                image_ai_payload={
                    "symbol": "BTCUSD",
                    "side": "BUY",
                    "order_type": "MARKET",
                    "entry_price": 77645.45,
                    "stop_loss": 76764.84,
                    "take_profits": [78523.57],
                    "confidence": 1.0,
                    "notes": [],
                },
            )

            self.assertEqual(result.signal.entry_price, 77645.45)
            self.assertFalse(any("Adjusted entry" in note for note in result.signal.notes))

    def test_ai_payload_recovers_btc_entry_from_spaced_ocr_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            config.allowed_symbols.append("BTCUSD")
            parser = SignalParser(config=config, ai_client=None)

            result = parser.parse(
                TelegramSignalMessage(
                    source_group="ALGO TRADING forex.",
                    message_id="11782",
                    raw_text="New",
                    image_path="11782.jpg",
                ),
                image_text=(
                    "BTCUSD, buy 0.10\n"
                    "Entry: 77 645.45\n"
                    "S/L: 76764.84\n"
                    "T/P: 78523.57\n"
                ),
                image_ai_payload={
                    "symbol": "BTCUSD",
                    "side": "BUY",
                    "order_type": "MARKET",
                    "entry_price": 645.45,
                    "stop_loss": 76764.84,
                    "take_profits": [78523.57],
                    "confidence": 1.0,
                    "notes": [],
                },
            )

            self.assertEqual(result.signal.entry_price, 77645.45)
            self.assertTrue(
                any("Recovered entry from OCR text" in note for note in result.signal.notes),
                result.signal.notes,
            )

    def test_ai_payload_prefers_entry_labeled_value_over_nearby_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            config.allowed_symbols.append("BTCUSD")
            parser = SignalParser(config=config, ai_client=None)

            result = parser.parse(
                TelegramSignalMessage(
                    source_group="ALGO TRADING forex.",
                    message_id="11784",
                    raw_text="New",
                    image_path="11784.jpg",
                ),
                image_text=(
                    "BTCUSD buy now\n"
                    "Entry: 77 645.45\n"
                    "Zone: 77600.00 - 77610.00\n"
                    "S/L: 76764.84\n"
                    "T/P: 78523.57\n"
                ),
                image_ai_payload={
                    "symbol": "BTCUSD",
                    "side": "BUY",
                    "order_type": "MARKET",
                    "entry_price": 645.45,
                    "stop_loss": 76764.84,
                    "take_profits": [78523.57],
                    "confidence": 1.0,
                    "notes": [],
                },
            )

            self.assertEqual(result.signal.entry_price, 77645.45)

    def test_heuristic_parser_handles_cross_prefix_before_sl(self) -> None:
        """✗SL 4590 — Unicode cross/ballot prefix must not block SL extraction."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            parser = SignalParser(config=build_config(tmp_path), ai_client=None)
            result = parser.parse(
                TelegramSignalMessage(
                    source_group="XAUUSD GOLD SIGNAL",
                    message_id="1",
                    raw_text="XAUUSD SELL 4580\n✗SL 4590\nTP 4560",
                )
            )
            self.assertEqual(result.signal.stop_loss, 4590.0)

    def test_heuristic_parser_cluster_noise_guard_blocks_execution(self) -> None:
        """Message with no prices but cluster context should get low confidence (< 0.45)."""
        # Match the exact format that MessageClusterAgent._enrich_message produces
        cluster_block = (
            "[CLUSTER CONTEXT]\nSymbol: XAUUSD\nSide: SELL\n"
            "Entry: 4580\nSL: 4591\nTP: 4560 4540\n[/CLUSTER CONTEXT]\n---\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            parser = SignalParser(config=build_config(tmp_path), ai_client=None)
            result = parser.parse(
                TelegramSignalMessage(
                    source_group="XAUUSD GOLD SIGNAL",
                    message_id="2",
                    raw_text=cluster_block + "Go selll",
                )
            )
            # Levels should be filled from cluster but confidence capped
            self.assertEqual(result.signal.stop_loss, 4591.0)
            self.assertLess(result.signal.confidence, 0.45, "Noise message must not exceed minimum_confidence=0.45")

    def test_heuristic_parser_custom_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            config.custom_buy_keywords = ["BULLISH", "UPWARD", "CALL"]
            config.custom_sell_keywords = ["BEARISH", "DOWNWARD", "PUT"]
            parser = SignalParser(config=config, ai_client=None)

            # Test custom buy keyword
            result_buy = parser.parse(
                TelegramSignalMessage(
                    source_group="Custom channel",
                    message_id="10",
                    raw_text="XAUUSD BULLISH NOW @ 2320 SL 2315 TP 2330",
                )
            )
            self.assertEqual(result_buy.signal.side, "BUY")

            # Test custom sell keyword
            result_sell = parser.parse(
                TelegramSignalMessage(
                    source_group="Custom channel",
                    message_id="11",
                    raw_text="XAUUSD BEARISH NOW @ 2320 SL 2325 TP 2310",
                )
            )
            self.assertEqual(result_sell.signal.side, "SELL")


if __name__ == "__main__":
    unittest.main()