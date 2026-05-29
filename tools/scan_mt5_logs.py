#!/usr/bin/env python3
import os
from pathlib import Path
import sys

def mt5_terminals():
    root = Path(os.environ.get('APPDATA','')) / 'MetaQuotes' / 'Terminal'
    if not root.exists():
        return []
    return [p for p in root.iterdir() if p.is_dir()]

def latest_log_for_terminal(terminal_dir: Path):
    log_dir = terminal_dir / 'MQL5' / 'Logs'
    if not log_dir.exists():
        return None
    logs = sorted(log_dir.glob('*.log'), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None

if __name__ == '__main__':
    terminals = mt5_terminals()
    if not terminals:
        print('No MT5 terminals found under APPDATA')
        sys.exit(1)
    for t in terminals:
        log = latest_log_for_terminal(t)
        if not log:
            continue
        print('Terminal:', t.name)
        print('Log:', log)
        try:
            data = log.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            data = log.read_text(encoding='cp1252', errors='ignore')
        lines = [l for l in data.splitlines() if 'TelegramSignalCopierEA' in l]
        if not lines:
            print('  No EA lines found in latest log')
        else:
            print('  Last 20 EA lines:')
            for line in lines[-20:]:
                print('   ', line)
        print('\n')
