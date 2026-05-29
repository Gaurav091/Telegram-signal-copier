"""Create a test TradeCommand and write it to the MT5 bridge inbox."""
from __future__ import annotations

from uuid import uuid4
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.models import TradeCommand


def main():
    config = AppConfig.from_env()
    executor = FileBridgeExecutor(config.bridge_inbox_dir, config.bridge_outbox_dir, timeout_seconds=config.mt5_bridge_timeout_seconds, symbol_suffix=config.mt5_symbol_suffix)
    req = str(uuid4())
    cmd = TradeCommand(
        request_id=req,
        source_group="ManualTest",
        message_id="manual-1",
        symbol="XAUUSD",
        action="BUY",
        order_type="MARKET",
        volume=float(config.default_volume),
        entry_price=4700.0,
        stop_loss=4690.0,
        take_profit=4710.0,
        take_profit_targets=[4710.0],
        comment="MANUAL|TEST",
    )
    res = executor.submit(cmd, wait_for_result=False)
    print("Wrote cmd", req, "to", config.bridge_inbox_dir)


if __name__ == '__main__':
    main()
