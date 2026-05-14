from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ParsedSignal, TradeCommand
from telegram_signal_copier.adapters.bridge import FileBridgeExecutor

cfg = AppConfig.from_env()
cfg.ensure_runtime_dirs()

# Build a simple parsed signal for XAUUSD
sig = ParsedSignal(
    source_group="Test",
    message_id="tsw-1",
    symbol="XAUUSD",
    side="BUY",
    entry_price=1800.0,
    stop_loss=1790.0,
    take_profits=[1810.0],
    confidence=0.95,
    raw_text="XAUUSD BUY 1800 SL 1790 TP 1810",
)

cmd = TradeCommand.from_signal(sig, volume=cfg.default_volume)
executor = FileBridgeExecutor(cfg.bridge_inbox_dir, cfg.bridge_outbox_dir, timeout_seconds=cfg.mt5_bridge_timeout_seconds, symbol_suffix=cfg.mt5_symbol_suffix)
res = executor.submit(cmd, wait_for_result=False)
print('Wrote command to inbox, request_id=', cmd.request_id)
print('Check file in', cfg.bridge_inbox_dir)
