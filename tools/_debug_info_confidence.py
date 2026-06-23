import re

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services.signals.heuristic_parse import heuristic_parse
from telegram_signal_copier.models import TelegramSignalMessage
from telegram_signal_copier.services.signal_patterns import SL_PATTERN, TP_PATTERN, ENTRY_PATTERN


config = AppConfig.from_env()


def make_msg(text: str) -> TelegramSignalMessage:
    return TelegramSignalMessage(
        source_group="test",
        message_id="1",
        raw_text=text,
        image_path=None,
        grouped_count=1,
        received_at="2026-06-19T12:00:00+00:00",
    )


tests = [
    "🤑🤑🤑🥳😎💪🚀",
    "Allhumdullah Morning Acc Manage MY Account Management Profit 5375$ Done Guys",
    "4156 Done",
    "congratulations 🎉🎉",
]


for t in tests:
    msg = make_msg(t)
    sig = heuristic_parse(config, msg, t)
    upper_text = t.upper()

    explicit_trade_markers_present = any(
        k in upper_text
        for k in ["BUY", "SELL", "LONG", "SHORT", "ENTRY", "AT", "SL", "TP", "TARGET"]
    )
    sl_tp_entry_markers_present = bool(
        SL_PATTERN.search(upper_text) or TP_PATTERN.search(upper_text) or ENTRY_PATTERN.search(upper_text)
    )
    celebration_noise = any(
        kw in upper_text
        for kw in ("CONGRATULATIONS", "CONGRATS", "DONE", "BOOKED", "🎉", "🥳", "🚀", "🤑")
    ) or bool(re.search(r"[\U0001F300-\U0001FAFF]", upper_text))

    print("=" * 80)
    print("TEXT:", repr(t))
    print("  sig.confidence:", sig.confidence)
    print("  explicit_trade_markers_present:", explicit_trade_markers_present)
    print("  sl_tp_entry_markers_present:", sl_tp_entry_markers_present)
    print("  celebration_noise:", celebration_noise)
    print("  extracted symbol/side/SL/TP/entry:",
          {"symbol": sig.symbol, "side": sig.side, "entry": sig.entry_price, "sl": sig.stop_loss, "tps": sig.take_profits})
