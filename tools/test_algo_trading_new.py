"""Test that 'New'/'Both New' captions from ALGO TRADING forex parse correctly."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services.signal_parser import SignalParser
from telegram_signal_copier.services.risk_engine import RiskEngine
from telegram_signal_copier.models import TelegramSignalMessage

cfg = AppConfig.from_env()
parser = SignalParser(config=cfg, ai_client=None)
risk = RiskEngine(config=cfg)

# Exact OCR text from message 11734 (XAUUSD SELL, T/P has OCR space artifact)
xauusd_ocr = "\n".join([
    "XAUUSD, sell 0.50",
    "",
    "4538.39 > 4539.45  53.00",
    "#1318902584 Open: 2026.05.19 08:45:00",
    "S/L: 4575.16 Swap: 0.00",
    "T/P: 4 491.53",
    "",
    "Comment: 100000",
])

# BTCUSD BUY with spaced numbers
btcusd_ocr = "\n".join([
    "BTCUSD, buy 0.01",
    "",
    "102500.00 > 102600.00 +100.00",
    "S/L: 101 000.00 Swap: 0.00",
    "T/P: 104 500.00",
    "",
    "Comment: 100001",
])

cases = [
    ("XAUUSD SELL New",    "ALGO TRADING forex.", "11734", "New",      xauusd_ocr),
    ("XAUUSD SELL BothNew","ALGO TRADING forex.", "11735", "Both New", xauusd_ocr),
    ("BTCUSD BUY New",     "ALGO TRADING forex.", "11736", "New",      btcusd_ocr),
]

all_ok = True
for label, source, msg_id, caption, ocr in cases:
    msg = TelegramSignalMessage(
        source_group=source,
        message_id=msg_id,
        raw_text=caption,
        image_path=None,
    )
    result = parser.parse(msg, image_text=ocr)
    s = result.signal
    dec = risk.evaluate(s)
    status = "OK" if dec.approved else "FAIL"
    if not dec.approved:
        all_ok = False
    print(f"[{status}] {label}")
    print(f"       parser={s.parser_name} sym={s.symbol} side={s.side} SL={s.stop_loss} TPs={s.take_profits} conf={s.confidence:.2f}")
    print(f"       decision={dec.status} reasons={dec.reasons}")
    print()

sys.exit(0 if all_ok else 1)
