#!/usr/bin/env python3
import sys, time, traceback
from pathlib import Path
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ParsedSignal, TradeCommand, ExecutionResult
from telegram_signal_copier.adapters.bridge import FileBridgeExecutor


def run_test(timeout_sec=10, simulate=True):
    cfg = AppConfig.from_env()
    cfg.ensure_runtime_dirs()
    executor = FileBridgeExecutor(cfg.bridge_inbox_dir, cfg.bridge_outbox_dir, timeout_seconds=timeout_sec, symbol_suffix=cfg.mt5_symbol_suffix)

    parsed = ParsedSignal(
        source_group="AutomatedTest",
        message_id="auto-1",
        symbol="XAUUSD",
        side="BUY",
        order_type="MARKET",
        entry_price=4700.0,
        stop_loss=4690.0,
        take_profits=[4710.0],
        confidence=1.0,
        raw_text="Automated test",
    )

    cmd = TradeCommand.from_signal(parsed, volume=cfg.default_volume)
    print("TEST_REQUEST_ID:", cmd.request_id)

    try:
        res = executor.submit(cmd, wait_for_result=True, timeout_seconds=timeout_sec)
        print("INITIAL_STATUS:", res.status)
    except Exception as exc:
        print("SUBMIT_EXCEPTION:", str(exc))
        traceback.print_exc()
        return 2

    if res.status == "NOT_CONSUMED" and simulate:
        out = cfg.bridge_outbox_dir
        out.mkdir(parents=True, exist_ok=True)
        lines = [
            f"request_id={cmd.request_id}",
            "status=EXECUTED",
            "message=Automated simulated execution",
            "ticket=AUTO-TEST-1",
            f"executed_price={cmd.entry_price or ''}",
            f"executed_at={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        ]
        out_path = out / f"{cmd.request_id}.result"
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("SIMULATED_RESULT_WRITTEN")
        final_lines = out_path.read_text(encoding="utf-8").splitlines()
        final = ExecutionResult.from_bridge_lines(final_lines)
        print("FINAL_STATUS:", final.status)
        print("FINAL_MESSAGE:", final.message)
    else:
        print("NO_SIMULATION_NEEDED")

    return 0


if __name__ == "__main__":
    timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    simulate = True if len(sys.argv) < 3 or sys.argv[2].lower() in ("1", "true", "yes") else False
    sys.exit(run_test(timeout, simulate))
