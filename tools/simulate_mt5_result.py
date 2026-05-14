#!/usr/bin/env python3
import time, sys
from pathlib import Path

from telegram_signal_copier.config import AppConfig


def main(delay_seconds=2):
    cfg = AppConfig.from_env()
    cfg.ensure_runtime_dirs()
    inbox = Path(cfg.bridge_inbox_dir)
    outbox = Path(cfg.bridge_outbox_dir)
    # wait for sample runner to write command file
    time.sleep(float(delay_seconds))
    cmd_files = sorted(inbox.glob("*.cmd"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not cmd_files:
        print("No command files found in inbox:", inbox)
        return 2
    cmd = cmd_files[0]
    text = cmd.read_text(encoding="utf-8").splitlines()
    vals = {}
    for line in text:
        key, sep, value = line.partition("=")
        if sep:
            vals[key.strip()] = value.strip()
    req_id = vals.get("request_id", "")
    executed_price = vals.get("entry_price", "")
    from datetime import datetime, timezone
    result_lines = [
        f"request_id={req_id}",
        "status=EXECUTED",
        "message=Simulated demo execution",
        "ticket=SIM-DEM-1",
        f"executed_price={executed_price}",
        f"executed_at={datetime.now(timezone.utc).isoformat()}",
    ]
    out_path = outbox / f"{req_id}.result"
    outbox.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")
    print("Wrote simulated result to", out_path)
    return 0


if __name__ == "__main__":
    delay = sys.argv[1] if len(sys.argv) > 1 else "2"
    sys.exit(main(delay))
