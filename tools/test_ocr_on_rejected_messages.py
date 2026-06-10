#!/usr/bin/env python
"""Test OCR extractor on simulated ALGO TRADING forex. messages.

Replays the 5 most recent rejected messages from ALGO TRADING forex.
to verify if local OCR extraction would have parsed them correctly.

Uses the raw_text and image metadata from pipeline logs to reconstruct
the messages and test parsing.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage, ParsedSignal
from telegram_signal_copier.services.signals.parser import SignalParser
from telegram_signal_copier.adapters.openai_client import OpenAIClient


def create_test_message(source_group: str, message_id: str, raw_text: str, has_image: bool = True) -> TelegramSignalMessage:
    """Create a mock TelegramSignalMessage for testing."""
    return TelegramSignalMessage(
        source_group=source_group,
        message_id=message_id,
        raw_text=raw_text,
        image_path="test_chart.jpg" if has_image else None,
    )


def test_ocr_extraction():
    """Test OCR extraction on the 5 rejected ALGO TRADING forex. messages."""
    config = AppConfig.from_env()
    
    # Create parser WITHOUT AI client to force OCR/heuristic fallback
    parser = SignalParser(config, ai_client=None)
    
    print("=" * 80)
    print("Testing Local OCR Extraction on Previously Rejected Messages")
    print("=" * 80)
    print(f"Config: MINIMUM_CONFIDENCE={config.minimum_confidence}")
    print(f"Allowed Symbols: {config.merged_allowed_symbols[:5]}...")
    print()
    
    # Test cases based on actual rejected messages from pipeline logs
    test_cases = [
        {
            "message_id": "11964",
            "raw_text": "Book\nNo chart image or text provided to extract trading signal.",
            "has_image": True,
            "expected_failure_reason": "No actionable text — requires AI vision to read chart",
        },
        {
            "message_id": "11965",
            "raw_text": "\nNo chart image or text provided to extract trading signal.",
            "has_image": True,
            "expected_failure_reason": "Empty text — requires AI vision to read chart",
        },
        {
            "message_id": "11966",
            "raw_text": "New\nXAUUSD, sell 0.50151.50\n\n4184.06 — 4181.03\n\n#1412407049\n\nOpen\n\n2026.06.10 05:45:00\n\nS/L:\n\n4207.16 Swap\n\n0.00\n\nT/P:\n\n4158.51\n\nComment: 100000",
            "has_image": True,
            "expected_failure_reason": "AI failed; heuristic should extract XAUUSD SELL with SL/TP",
        },
        {
            "message_id": "11967",
            "raw_text": "New\nNo chart image or text provided to extract trading signal.",
            "has_image": True,
            "expected_failure_reason": "Caption only — requires AI vision to read chart",
        },
        {
            "message_id": "11968",
            "raw_text": "XAUUSD, sell 0.50151.50\n\n4184.06 — 4181.03\n\n#1412407049\n\nOpen\n\n2026.06.10 05:45:00\n\nS/L:\n\n4207.16 Swap\n\n0.00\n\nT/P:\n\n4158.51\n\nComment: 100000",
            "has_image": True,
            "expected_failure_reason": "Heuristic should extract XAUUSD SELL SL=4207.16 TP=4158.51",
        },
    ]
    
    results = []
    
    for i, tc in enumerate(test_cases, 1):
        print(f"\n{'─' * 80}")
        print(f"Test Case {i}: Message ID {tc['message_id']}")
        print(f"{'─' * 80}")
        print(f"Raw Text (first 200 chars): {tc['raw_text'][:200]}")
        print(f"Has Image: {tc['has_image']}")
        print(f"Expected: {tc['expected_failure_reason']}")
        print()
        
        message = create_test_message(
            source_group="ALGO TRADING forex.",
            message_id=tc["message_id"],
            raw_text=tc["raw_text"],
            has_image=tc["has_image"],
        )
        
        # Parse without AI (simulates AI failure scenario)
        result = parser.parse(message, image_text="", image_ai_payload=None)
        signal = result.signal
        
        print(f"✓ Parser Used: {signal.parser_name}")
        print(f"✓ Symbol:      {signal.symbol}")
        print(f"✓ Side:        {signal.side}")
        print(f"✓ Entry:       {signal.entry_price}")
        print(f"✓ Stop Loss:   {signal.stop_loss}")
        print(f"✓ Take Profits:{signal.take_profits}")
        print(f"✓ Confidence:  {signal.confidence:.2f}")
        print(f"✓ Used AI:     {result.used_ai}")
        print(f"✓ Notes:")
        for note in signal.notes[:5]:
            print(f"    - {note}")
        
        # Determine if this would be accepted or rejected
        rejection_reasons = []
        if not signal.symbol:
            rejection_reasons.append("Missing symbol")
        if not signal.side:
            rejection_reasons.append("Missing side")
        if not signal.stop_loss:
            rejection_reasons.append("Missing stop loss")
        if not signal.take_profits:
            rejection_reasons.append("Missing take profit")
        if signal.confidence < config.minimum_confidence:
            rejection_reasons.append(f"Confidence {signal.confidence:.2f} below minimum {config.minimum_confidence}")
        
        if rejection_reasons:
            print(f"\n✗ REJECTED: {'; '.join(rejection_reasons)}")
            status = "REJECTED"
        else:
            print(f"\n✓ ACCEPTED — Would be sent to MT5 for execution")
            status = "ACCEPTED"
        
        results.append({
            "message_id": tc["message_id"],
            "status": status,
            "symbol": signal.symbol,
            "side": signal.side,
            "confidence": signal.confidence,
            "rejection_reasons": rejection_reasons,
        })
    
    # Summary
    print(f"\n\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    accepted = sum(1 for r in results if r["status"] == "ACCEPTED")
    rejected = sum(1 for r in results if r["status"] == "REJECTED")
    print(f"Total Messages:  {len(results)}")
    print(f"Accepted:        {accepted} ({accepted/len(results)*100:.0f}%)")
    print(f"Rejected:        {rejected} ({rejected/len(results)*100:.0f}%)")
    print()
    
    for r in results:
        icon = "✓" if r["status"] == "ACCEPTED" else "✗"
        print(f"{icon} Msg {r['message_id']:>6}: {r['status']:<10} | Symbol: {str(r['symbol']):<10} | Side: {str(r['side']):<6} | Conf: {r['confidence']:.2f}")
        if r["rejection_reasons"]:
            for reason in r["rejection_reasons"]:
                print(f"         └─ {reason}")
    
    print(f"\n{'=' * 80}")
    print("CONCLUSION")
    print(f"{'=' * 80}")
    if accepted > 0:
        print(f"✓ {accepted} message(s) that were previously REJECTED are now ACCEPTED")
        print("  → These would be sent to MT5 for execution")
    if rejected > 0:
        print(f"✗ {rejected} message(s) still REJECTED")
        print("  → These require AI vision or better OCR preprocessing")
        print("  → Consider updating Tesseract language packs or image preprocessing")
    
    return accepted, rejected


if __name__ == "__main__":
    accepted, rejected = test_ocr_extraction()
    sys.exit(0 if accepted > 0 else 1)
