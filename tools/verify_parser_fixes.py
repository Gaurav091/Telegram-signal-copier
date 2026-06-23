"""Verify parser fixes against actual rejected messages from pipeline logs."""
import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services.signals.heuristic import heuristic_parse
from telegram_signal_copier.models import TelegramSignalMessage

def make_message(text, source="test", msg_id="1", image_path=None):
    return TelegramSignalMessage(
        source_group=source,
        message_id=msg_id,
        raw_text=text,
        image_path=image_path,
        grouped_count=1,
        received_at="2026-06-19T12:00:00+00:00",
    )

def main():
    config = AppConfig.from_env()

    # Test cases from actual rejected messages
    test_cases = [
        # Symbol detection: should NOT parse entry prices as symbols
        ("INSIDER TRADING", "BUY Entry range: 4525.0-4532.0 Entry: 4525.0 SL: 4505.0 TP: 4540.0", "XAUUSD"),
        ("Forex Market King", "AD\nBUY\nEntry: 4198.0\nSL: 4190.0\nTP: 4210.0", None),  # 4190 was parsed as symbol before

        # Multi-line SL extraction
        ("Star Trading", "XAUUSD SELL\nSL:\n4518.0\nTP:\n4500.0", None),
        ("FOREX FOCUS", "XAUUSD BUY\nSL:\n4158.0\nTP:\n4178.0", None),

        # Informational messages that should be skipped
        ("GTA VIP", "70pips fly ✈️🤑🥳😎💪🚀 don't forget to collect or set be", None),
        ("GTA VIP", "🤑🤑🤑🥳😎💪🚀", None),
        ("FX VIP CLUB", "40 PIPS RUNNING 🔥🔥🔥🔥", None),
        ("Star Trading", "Allhumdullah Morning Acc Manage MY Account Management Profit 5375$ Done Guys", None),

        # Valid ALGO TRADING forex signals (must NOT break)
        ("ALGO TRADING forex.", "New", None),  # This is a caption that triggers MT5 screenshot parse

        # Valid GTA range signals (must NOT break)
        ("GTA VIP || 3.0", "XAUUSD BUY\nEntry: 4500-4510\nSL: 4490\nTP: 4520\nTP: 4530", None),

        # Valid signal with SL/TP on same line (must NOT break)
        ("XAUUSD GOLD SIGNAL", "XAUUSD SELL\nSL: 4533\nTP1: 4510\nTP2: 4490", None),
    ]

    print("=== Parser Fix Verification ===\n")
    improved = 0
    total = len(test_cases)

    for source, text, expected_symbol in test_cases:
        msg = make_message(text, source=source)
        signal = heuristic_parse(config, msg, text)

        has_symbol = signal.symbol is not None
        has_side = signal.side is not None
        has_sl = signal.stop_loss is not None
        has_tp = bool(signal.take_profits)

        status = "✅" if (has_symbol and has_side) else "⚠️"
        if "fly" in text or "🤑" in text or "PIPS RUNNING" in text or "Done Guys" in text:
            # These should be marked as trade management (confidence 0)
            if signal.confidence == 0.0:
                status = "✅ (correctly filtered)"
                improved += 1
            else:
                status = "⚠️ (should be filtered)"
        elif has_symbol and has_side and (has_sl or has_tp):
            improved += 1

        print(f"{status} [{source}]")
        print(f"  text: {text[:80]}...")
        print(f"  symbol={signal.symbol} side={signal.side} entry={signal.entry_price} SL={signal.stop_loss} TP={signal.take_profits} conf={signal.confidence:.2f}")
        if expected_symbol and signal.symbol != expected_symbol:
            print(f"  ⚠️ Expected symbol={expected_symbol}, got {signal.symbol}")
        print()

    print(f"\nImproved: {improved}/{total} test cases")

if __name__ == "__main__":
    main()