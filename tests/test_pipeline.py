import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ExecutionResult, ParsedSignal, TelegramSignalMessage, TradeCommand
from telegram_signal_copier.services.image_processor import ImageProcessor
from telegram_signal_copier.services.pipeline import CopierPipeline
from telegram_signal_copier.services.risk_engine import RiskEngine
from telegram_signal_copier.services.signal_parser import SignalParser


class _UnusedImageProcessor:
    def extract_signal_context(self, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("image processing should not run for forced trade updates")


class _UnusedSignalParser:
    ai_client = None

    def _heuristic_parse(self, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("heuristic parser should not run for forced trade updates")

    def parse(self, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("full parser should not run for forced trade updates")


class _StaticIntentClient:
    def __init__(self, intent: str, confidence: float, reasoning: str = "") -> None:
        self._intent = intent
        self._confidence = confidence
        self._reasoning = reasoning

    def classify_intent(self, *args, **kwargs):
        return {
            "intent": self._intent,
            "confidence": self._confidence,
            "reasoning": self._reasoning,
        }


class _IntentOnlySignalParser:
    def __init__(self, ai_client) -> None:
        self.ai_client = ai_client

    def _heuristic_parse(self, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("heuristic parser should not run for skipped informational messages")

    def parse(self, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("full parser should not run for skipped informational messages")


def build_config(tmp_path: Path) -> AppConfig:
    bridge_root = tmp_path / "Common" / "Files" / "TelegramSignalCopierBridge"
    return AppConfig(
        project_root=tmp_path,
        bridge_inbox_dir=bridge_root,
        bridge_outbox_dir=bridge_root / "outbox",
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
    def test_file_bridge_retries_symbol_selection_errors(self) -> None:
        result = ExecutionResult(
            request_id="req-1",
            status="ERROR",
            message="Failed to select symbol in terminal",
        )

        self.assertTrue(FileBridgeExecutor._should_retry_symbol_selection(result))

    def test_file_bridge_symbol_retry_candidates_include_index_aliases(self) -> None:
        executor = FileBridgeExecutor(Path("."), Path("."), symbol_suffix="m")

        candidates = executor._symbol_retry_candidates("NAS100m")

        self.assertIn("NAS100m", candidates)
        self.assertIn("USTECm", candidates)
        self.assertIn("NQ100m", candidates)
        self.assertIn("US100m", candidates)

    def test_trade_command_bridge_payload_includes_submitted_epoch(self) -> None:
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

        payload = command.to_bridge_payload()

        self.assertIn("submitted_epoch", payload)
        self.assertTrue(payload["submitted_epoch"].isdigit())

    def test_file_bridge_reports_not_consumed_when_command_stays_in_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            signal = SignalParser(config=config, ai_client=None).parse(
                TelegramSignalMessage(
                    source_group="Gold Expertise",
                    message_id="26019",
                    raw_text="XAUUSD SELL LIMIT @4718 SL 4726.56 TP1 4710 TP2 4703 TP3 4695",
                )
            ).signal
            command = TradeCommand.from_signal(signal, volume=0.10)
            executor = FileBridgeExecutor(config.bridge_inbox_dir, config.bridge_outbox_dir, timeout_seconds=0.01)

            result = executor.submit(command)

            self.assertEqual(result.status, "NOT_CONSUMED")
            self.assertIn("still pending", result.message)

    def test_file_bridge_mirrors_to_legacy_inbox_when_root_not_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            signal = SignalParser(config=config, ai_client=None).parse(
                TelegramSignalMessage(
                    source_group="Gold Expertise",
                    message_id="26020",
                    raw_text="XAUUSD SELL LIMIT @4718 SL 4726.56 TP1 4710 TP2 4703 TP3 4695",
                )
            ).signal
            command = TradeCommand.from_signal(signal, volume=0.10)
            executor = FileBridgeExecutor(
                config.bridge_inbox_dir,
                config.bridge_outbox_dir,
                timeout_seconds=0.01,
                legacy_inbox_mirror_delay_seconds=0.0,
            )

            result = executor.submit(command)

            self.assertEqual(result.status, "NOT_CONSUMED")
            self.assertTrue((config.bridge_inbox_dir / f"{command.request_id}.cmd").exists())
            self.assertTrue((config.bridge_inbox_dir / "inbox" / f"{command.request_id}.cmd").exists())
            self.assertTrue(
                (tmp_path / "Common" / "Files" / f"TelegramSignalCopierBridge__{command.request_id}.txt").exists()
            )
            self.assertIn(
                command.request_id,
                (config.bridge_inbox_dir / "command_queue.txt").read_text(encoding="utf-8"),
            )

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
                    raw_text="BUY GOLD NOW @ 4520 SL 4510 TP1 4540 TP2 4550",
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

    def test_risk_engine_rejects_out_of_range_xau_signal(self) -> None:
        config = build_config(Path("."))
        engine = RiskEngine(config=config)

        decision = engine.evaluate(
            ParsedSignal(
                source_group="ALGO TRADING forex.",
                message_id="bad-range-1",
                symbol="XAUUSD",
                side="BUY",
                order_type="MARKET",
                entry_price=2347.0,
                stop_loss=2340.0,
                take_profits=[2355.0, 2362.0],
                confidence=0.90,
                raw_text="BUY XAUUSD 2347 SL 2340 TP 2355",
            )
        )

        self.assertEqual(decision.status, "REJECTED")
        self.assertTrue(any("outside expected range" in reason for reason in decision.reasons))

    def test_risk_engine_rejects_tight_tp_distance(self) -> None:
        config = build_config(Path("."))
        engine = RiskEngine(config=config)

        decision = engine.evaluate(
            ParsedSignal(
                source_group="VIP Gold",
                message_id="tight-stops-1",
                symbol="XAUUSD",
                side="BUY",
                order_type="MARKET",
                entry_price=4540.0,
                stop_loss=4528.0,
                take_profits=[4543.0],
                confidence=0.95,
                raw_text="XAUUSD BUY 4540 SL 4528 TP 4543",
            )
        )

        self.assertEqual(decision.status, "REJECTED")
        self.assertTrue(any("TP1 distance" in reason for reason in decision.reasons))

    def test_risk_engine_rejects_missing_entry_when_tp_sl_band_is_too_tight(self) -> None:
        config = build_config(Path("."))
        engine = RiskEngine(config=config)

        decision = engine.evaluate(
            ParsedSignal(
                source_group="GOLD VIP SIGNALS",
                message_id="tight-band-1",
                symbol="XAUUSD",
                side="BUY",
                order_type="MARKET",
                entry_price=None,
                stop_loss=4528.0,
                take_profits=[4543.0, 1.0],
                confidence=0.85,
                raw_text="BUY XAUUSD SL 4528 TP1 4543 TP2 1.0",
            )
        )

        self.assertEqual(decision.status, "REJECTED")
        self.assertTrue(any("band" in reason for reason in decision.reasons))

    def test_pipeline_skips_trade_update_caption_with_image_without_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            executor = Mock(spec=FileBridgeExecutor)
            pipeline = CopierPipeline(
                config=config,
                image_processor=_UnusedImageProcessor(),
                signal_parser=_UnusedSignalParser(),
                risk_engine=RiskEngine(config=config),
                executor=executor,
            )

            outcome = pipeline.process_message(
                TelegramSignalMessage(
                    source_group="ALGO TRADING forex.",
                    message_id="11750",
                    raw_text="Exit both",
                    image_path=tmp_path / "11750.jpg",
                )
            )

            self.assertEqual(outcome.decision.status, "SKIPPED")
            self.assertIsNone(outcome.execution_result)
            self.assertTrue(any("Trade update" in reason for reason in outcome.decision.reasons))
            executor.submit.assert_not_called()

    def test_pipeline_skips_pips_done_trade_update_with_image_without_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            executor = Mock(spec=FileBridgeExecutor)
            pipeline = CopierPipeline(
                config=config,
                image_processor=_UnusedImageProcessor(),
                signal_parser=_UnusedSignalParser(),
                risk_engine=RiskEngine(config=config),
                executor=executor,
            )

            outcome = pipeline.process_message(
                TelegramSignalMessage(
                    source_group="Crypto with kevin 3.0",
                    message_id="9601..9605",
                    raw_text="100 pips done on sell signal",
                    image_path=tmp_path / "9605.jpg",
                )
            )

            self.assertEqual(outcome.decision.status, "SKIPPED")
            self.assertIsNone(outcome.execution_result)
            self.assertTrue(any("Trade update" in reason for reason in outcome.decision.reasons))
            executor.submit.assert_not_called()

    def test_pipeline_skips_cancel_order_trade_update_with_image_without_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            executor = Mock(spec=FileBridgeExecutor)
            pipeline = CopierPipeline(
                config=config,
                image_processor=_UnusedImageProcessor(),
                signal_parser=_UnusedSignalParser(),
                risk_engine=RiskEngine(config=config),
                executor=executor,
            )

            outcome = pipeline.process_message(
                TelegramSignalMessage(
                    source_group="Crypto with kevin 3.0",
                    message_id="9231..9233",
                    raw_text="Cancel this order",
                    image_path=tmp_path / "9233.jpg",
                )
            )

            self.assertEqual(outcome.decision.status, "SKIPPED")
            self.assertIsNone(outcome.execution_result)
            self.assertTrue(any("Trade update" in reason for reason in outcome.decision.reasons))
            executor.submit.assert_not_called()

    def test_pipeline_skips_stop_loss_update_caption_with_image_without_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            executor = Mock(spec=FileBridgeExecutor)
            pipeline = CopierPipeline(
                config=config,
                image_processor=_UnusedImageProcessor(),
                signal_parser=_UnusedSignalParser(),
                risk_engine=RiskEngine(config=config),
                executor=executor,
            )

            outcome = pipeline.process_message(
                TelegramSignalMessage(
                    source_group="Adam Gold Master",
                    message_id="5625",
                    raw_text="Just Kiss My Stop Loss And Fly",
                    image_path=tmp_path / "5625.jpg",
                )
            )

            self.assertEqual(outcome.decision.status, "SKIPPED")
            self.assertIsNone(outcome.execution_result)
            self.assertTrue(any("Trade update" in reason for reason in outcome.decision.reasons))
            executor.submit.assert_not_called()

    def test_pipeline_skips_text_only_high_confidence_informational_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = build_config(tmp_path)
            executor = Mock(spec=FileBridgeExecutor)
            pipeline = CopierPipeline(
                config=config,
                image_processor=_UnusedImageProcessor(),
                signal_parser=_IntentOnlySignalParser(
                    _StaticIntentClient(
                        intent="INFORMATIONAL",
                        confidence=0.90,
                        reasoning="Pure commentary or promo message",
                    )
                ),
                risk_engine=RiskEngine(config=config),
                executor=executor,
            )

            outcome = pipeline.process_message(
                TelegramSignalMessage(
                    source_group="XAUUSD GOLD SIGNAL",
                    message_id="32963",
                    raw_text="[CLUSTER CONTEXT] Symbol: XAUUSD [/CLUSTER CONTEXT]\n---\nNot Related to Us\n---\nSTAY ACTIVE FOR SIGNAL",
                )
            )

            self.assertEqual(outcome.decision.status, "SKIPPED")
            self.assertIsNone(outcome.execution_result)
            self.assertTrue(any("Informational" in reason for reason in outcome.decision.reasons))
            executor.submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()