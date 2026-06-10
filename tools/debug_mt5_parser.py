#!/usr/bin/env python
"""Debug script for MT5 screenshot parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from telegram_signal_copier.services.signals.heuristic import _parse_mt5_screenshot
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage
import tempfile

tmp = tempfile.mkdtemp()
config = AppConfig.from_env(Path(tmp))
msg = TelegramSignalMessage(source_group='TEST', message_id='11776', raw_text='', image_path='11776.jpg')
text = (
    "XAUUSD, sell 0.50 350\n"
    "4 499.54 - 4 499.47\n"
    "#1338763137 Open: 2026.05.22 17:30:00\n"
    "S/L: 4534.51 Swap: 0.00\n"
    "T/P: 4 452.20\n"
    "Comment: 100004"
)

result = _parse_mt5_screenshot(config, msg, text)
if result:
    print(f'Symbol: {result.symbol}')
    print(f'Side: {result.side}')
    print(f'Entry: {result.entry_price}')
    print(f'SL: {result.stop_loss}')
    print(f'TP: {result.take_profits}')
else:
    print("Parser returned None")
