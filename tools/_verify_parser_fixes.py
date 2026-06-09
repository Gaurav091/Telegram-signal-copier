"""Verify parser fixes against rejected signal patterns."""
from telegram_signal_copier.services.signal_parser import SignalParser
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage
import tempfile, pathlib

tmp = pathlib.Path(tempfile.mkdtemp())
cfg = AppConfig(
    project_root=tmp, bridge_inbox_dir=tmp / "b", bridge_outbox_dir=tmp / "bo",
    telegram_api_id=None, telegram_api_hash=None, telegram_phone_number=None,
    telegram_session_name="t", telegram_sources=[], openai_api_key=None,
    openai_model="x", openai_base_url="x", minimum_confidence=0.45,
    default_volume=0.01, allowed_symbols=["XAUUSD","EURUSD","GBPUSD","BTCUSD"],
    dry_run=True, approval_required_below=0.85, poll_interval_seconds=1,
)
p = SignalParser(config=cfg, ai_client=None)

tests = [
    ("promo_vip", "GOLD Sell NOW I am going to add 15 members in my vip for free trail .. hurry up"),
    ("trade_mgmt", "GOLD SELL HIT TP1+90 pips Move SL to your entry and close bad entry"),
    ("unicode_sl", "XAUUSD SELL 4320\n\u274cSL 4335\n\u26a1TP 4310\n\u26a1TP 4300"),
    ("ellipsis_sl_tp", "GOLD sell\nSl \u2026. 4330\nTp \u2026. 4310"),
    ("multi_target", "Gold buy @4511-4502\nTarget- 4514, 4520, 4530\nSl- 4499"),
    ("tg_shorthand", "XAUUSD BUY 4300\nTG1 4310\nTG2 4320\nSL 4290"),
    ("stop_keyword", "GOLD SELL 4320\nStop 4335\nTP 4310"),
    ("sl_here_emoji", "ACTIVE XAUUSD GOLD BUY TP/SL HERE\ud83d\udc46"),
]

print(f"{'Test':<20} {'Side':<6} {'SL':>8} {'TPs':<25} {'Conf':>5} {'Note'}")
print("-" * 90)
for name, text in tests:
    msg = TelegramSignalMessage(source_group="TEST", message_id="1", raw_text=text)
    r = p.parse(msg)
    note = r.signal.notes[0][:40] if r.signal.notes else ""
    print(f"{name:<20} {str(r.signal.side):<6} {str(r.signal.stop_loss):>8} {str(r.signal.take_profits):<25} {r.signal.confidence:>5.2f} {note}")
