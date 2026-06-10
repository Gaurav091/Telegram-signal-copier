#!/usr/bin/env python
"""Test script for local OCR signal extraction.

Usage:
    python tools/test_ocr_extractor.py <image_path>

Tests the OCR extractor on a chart image and prints the extracted signal.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage
from telegram_signal_copier.services.signals.ocr_extractor import extract_signal_from_image


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_ocr_extractor.py <image_path>")
        print("\nExample:")
        print("  python test_ocr_extractor.py bridge/11968.jpg")
        sys.exit(1)

    image_path = sys.argv[1]
    if not Path(image_path).exists():
        print(f"Error: Image not found: {image_path}")
        sys.exit(1)

    # Load config
    config = AppConfig.from_env()

    # Create a mock message
    message = TelegramSignalMessage(
        source_group="TEST GROUP",
        message_id="test_001",
        raw_text="",
        image_path=image_path,
    )

    # Extract signal
    print(f"Processing image: {image_path}")
    print("=" * 60)
    signal = extract_signal_from_image(config, message)

    # Print results
    print(f"Symbol:          {signal.symbol}")
    print(f"Side:            {signal.side}")
    print(f"Order Type:      {signal.order_type}")
    print(f"Entry Price:     {signal.entry_price}")
    print(f"Stop Loss:       {signal.stop_loss}")
    print(f"Take Profits:    {signal.take_profits}")
    print(f"Confidence:      {signal.confidence:.2f}")
    print(f"Parser:          {signal.parser_name}")
    print(f"Image Used:      {signal.image_used}")
    print(f"\nNotes:")
    for note in signal.notes:
        print(f"  - {note}")
    print(f"\nRaw OCR Text (first 500 chars):")
    print(signal.raw_text[:500] if signal.raw_text else "(empty)")


if __name__ == "__main__":
    main()
