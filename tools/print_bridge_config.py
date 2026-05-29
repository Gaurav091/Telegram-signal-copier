from telegram_signal_copier.config import AppConfig
c = AppConfig.from_env()
print('bridge_inbox_dir=', c.bridge_inbox_dir)
print('bridge_outbox_dir=', c.bridge_outbox_dir)
print('mt5_bridge_timeout_seconds=', c.mt5_bridge_timeout_seconds)
print('mt5_symbol_suffix=', repr(c.mt5_symbol_suffix))
print('dry_run=', c.dry_run)
