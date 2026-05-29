"""Watch EA status file and bridge inbox for activity.

Prints changes to ea_status.txt and alerts when .cmd files are present
but EA's last_request_id remains empty.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from telegram_signal_copier.config import AppConfig


def parse_status(path: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    except Exception:
        pass
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()

    config = AppConfig.from_env()
    bridge = config.bridge_inbox_dir
    status_path = bridge / "ea_status.txt"
    last: dict[str, str] = {}
    print("EA status watcher watching", status_path)
    while True:
        try:
            if status_path.exists():
                cur = parse_status(status_path)
                if cur != last:
                    # Print changes
                    for k, v in cur.items():
                        if last.get(k) != v:
                            print(f"ea_status {k} -> {v}")
                    last = cur

                # If EA reports no last_request_id but there are commands, warn
                last_req = cur.get("last_request_id", "")
                cmds = list(bridge.glob("*.cmd"))
                if (not last_req) and cmds:
                    print(f"WARNING: {len(cmds)} .cmd in bridge but EA last_request_id empty")
            else:
                print("ea_status file not found at", status_path)
        except Exception as exc:
            print("ea_status_watcher error:", exc)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
