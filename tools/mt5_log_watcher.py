"""Continuous MT5 log watcher.

Watches the MT5 terminal logs for lines mentioning the EA or bridge activity
and prints matches to stdout. Designed to run in a background terminal.

Usage: python tools/mt5_log_watcher.py --interval 5
"""
from __future__ import annotations

import argparse
import time
import os
from pathlib import Path
from telegram_signal_copier.config import AppConfig


KEYWORDS = [
    "TelegramSignalCopierEA",
    "ProcessBridge",
    "ReadTrade",
    "WriteResult",
    "inbox/*.cmd",
    "NOT_CONSUMED",
]


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


def find_logs_dir_from_status(status_path: Path) -> Path | None:
    st = parse_status(status_path)
    td = st.get("terminal_data_path")
    if td:
        p = Path(td) / "MQL5" / "Logs"
        if p.exists():
            return p
    # fallback: search APPDATA MetaQuotes Terminal folders for MQL5/Logs
    root = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "MetaQuotes" / "Terminal"
    best = None
    for candidate in root.iterdir() if root.exists() else []:
        p = candidate / "MQL5" / "Logs"
        if p.exists():
            best = p
            break
    return best


def watch(logs_dir: Path, interval: float, keywords: list[str]) -> None:
    print("MT5 log watcher: watching", logs_dir)
    last_counts: dict[Path, int] = {}
    while True:
        try:
            if not logs_dir.exists():
                time.sleep(interval)
                continue
            for f in sorted(logs_dir.glob("*.log")) + sorted(logs_dir.glob("*.txt")):
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                lines = text.splitlines()
                prev = last_counts.get(f, 0)
                if len(lines) <= prev:
                    continue
                new_lines = lines[prev:]
                last_counts[f] = len(lines)
                matches = [l for l in new_lines if any(k in l for k in keywords)]
                if matches:
                    print(f"[{f.name}] {len(matches)} match(es):")
                    for m in matches:
                        print(m)
        except Exception as exc:
            print("mt5_log_watcher error:", exc)
        time.sleep(interval)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()

    config = AppConfig.from_env()
    status_path = config.bridge_inbox_dir / "ea_status.txt"
    logs_dir = find_logs_dir_from_status(status_path) or (Path(os.getenv("APPDATA", "")) / "MetaQuotes" / "Terminal")
    if isinstance(logs_dir, Path) and logs_dir.name == "Terminal":
        # not a direct logs folder; pick first found logs subfolder
        cand = None
        for t in logs_dir.iterdir() if logs_dir.exists() else []:
            p = t / "MQL5" / "Logs"
            if p.exists():
                cand = p
                break
        if cand:
            logs_dir = cand

    if not logs_dir or not logs_dir.exists():
        print("No MT5 logs directory found. Exiting.")
        return

    watch(logs_dir, args.interval, KEYWORDS)


if __name__ == "__main__":
    main()
