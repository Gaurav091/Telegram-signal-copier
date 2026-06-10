#!/usr/bin/env python
"""End-to-End Bridge Verification Script.

Submits a test trade command via FileBridgeExecutor and waits for the MT5 EA to process it.
"""
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.adapters.bridge import FileBridgeExecutor
from telegram_signal_copier.models import TradeCommand

def main():
    print("=" * 80)
    print("END-TO-END BRIDGE VERIFICATION")
    print("=" * 80)
    
    try:
        config = AppConfig.from_env()
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return

    print(f"✅ Config Loaded")
    print(f"   Bridge Inbox : {config.bridge_inbox_dir}")
    print(f"   Bridge Outbox: {config.bridge_outbox_dir}")
    
    if not config.bridge_inbox_dir.exists():
        print(f"❌ Inbox directory does not exist: {config.bridge_inbox_dir}")
        return

    executor = FileBridgeExecutor(
        inbox_dir=config.bridge_inbox_dir,
        outbox_dir=config.bridge_outbox_dir,
        symbol_suffix=config.mt5_symbol_suffix,
    )

    request_id = f"e2e_verify_{int(time.time())}"
    
    cmd = TradeCommand(
        request_id=request_id,
        submitted_at=datetime.now(timezone.utc).isoformat(),
        source_group='E2E_TEST',
        message_id='99999',
        symbol='XAUUSD',
        action='BUY',
        order_type='MARKET',
        volume=0.01,
        entry_price=None,
        stop_loss=4100.0,
        take_profit=4200.0,
        take_profit_targets=[4200.0],
        comment='TG|E2E_VERIFY|99999'
    )

    print(f"\n🚀 Submitting command: {request_id}")
    try:
        result = executor.submit(cmd)
        print(f"   Status: {result.status}")
    except Exception as e:
        print(f"❌ Submission failed: {e}")
        import traceback
        traceback.print_exc()
        return

    cmd_file = config.bridge_inbox_dir / f"{request_id}.cmd"
    result_file = config.bridge_outbox_dir / f"{request_id}.result"

    if not cmd_file.exists():
        print(f"❌ Command file was not created: {cmd_file}")
        return
    
    print(f"✅ Command file created: {cmd_file.name}")
    print(f"⏳ Waiting for MT5 EA to process (max 30s)...")

    for i in range(30):
        time.sleep(1)
        if result_file.exists():
            print(f"\n✅ SUCCESS! EA processed command in {i+1}s")
            print("-" * 80)
            print(result_file.read_text())
            print("-" * 80)
            return
        
        if i % 5 == 0:
            print(f"   ... still waiting ({i+1}s)")

    print(f"\n❌ TIMEOUT. EA did not process command within 30s.")
    print(f"   Check MT5 'Experts' tab for errors.")
    print(f"   Ensure EA is attached and Algo Trading is ON.")
    print(f"   Ensure EA Input 'BridgeFolderName' matches: {config.bridge_inbox_dir.name}")

if __name__ == "__main__":
    main()
