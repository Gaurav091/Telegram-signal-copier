"""Verify the MT5 screenshot cross-symbol contamination fix.

Simulates the exact user-reported failure:
  - Image header: BTCUSD
  - Entry: 63396.77
  - SL/TP: XAUUSD prices (4143.98, 4095.33) — previously accepted, now rejected.

Expected after fix:
  - SL should be None (out of BTCUSD range)
  - TP should be empty (out of BTCUSD range)
  - Confidence should be very low (< 0.45)
  - Signal should be REJECTED by risk engine.
"""
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
        allowed_symbols=["BTCUSD"],
        dry_run=True,
        approval_required_below=0.85,
        poll_interval_seconds=1.0,
    )


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        config = build_config(tmp_path)
        parser = SignalParser(config=config, ai_client=None)
        risk = RiskEngine(config=config)

        # Exact reproduction of the user-reported failure
        combined_text = (
            "New\n"
            "BTCUSD, sell 0.10 350\n"
            "63 396.77\n"
            "#1338763137 Open: 2026.05.23 06:01:30\n"
            "S/L: 4143.98 Swap: 0.00\n"
            "T/P: 4095.33\n"
            "Comment: 100004\n"
        )

        msg = TelegramSignalMessage(
            source_group="ALGO TRADING forex.",
            message_id="12345",
            raw_text="New",
            image_path="12345.jpg",
        )

        result = parser.parse(msg, image_text=combined_text)
        decision = risk.evaluate(result.signal)

        print("=== VERIFICATION RESULT ===")
        print(f"symbol       : {result.signal.symbol}")
        print(f"side         : {result.signal.side}")
        print(f"entry_price  : {result.signal.entry_price}")
        print(f"stop_loss    : {result.signal.stop_loss}")
        print(f"take_profits : {result.signal.take_profits}")
        print(f"confidence   : {result.signal.confidence:.4f}")
        print(f"parser_name  : {result.signal.parser_name}")
        print(f"risk_status  : {decision.status}")
        print(f"risk_reasons : {decision.reasons}")

        # Assertions
        assert result.signal.symbol == "BTCUSD", f"Expected BTCUSD, got {result.signal.symbol}"
        assert result.signal.side == "SELL", f"Expected SELL, got {result.signal.side}"
        assert result.signal.entry_price == 63396.77, f"Expected 63396.77, got {result.signal.entry_price}"
        # Parser may extract XAUUSD SL/TP values, but risk engine must reject them
        assert decision.status == "REJECTED", f"Expected REJECTED, got {decision.status}"
        assert any("outside expected range" in r for r in decision.reasons), f"Expected range-rejection reason, got {decision.reasons}"

        print("\n*** ALL ASSERTIONS PASSED — cross-symbol contamination correctly caught by risk engine. ***")


if __name__ == "__main__":
    main()