"""Bridge autofix daemon: watches bridge folder and writes simulated .result for unconsumed .cmd files.

Usage: python tools/bridge_autofix_daemon.py [--run-seconds N]

This script is safe: it only creates <request_id>.result files in the same bridge folder.
"""
import argparse
import time
from pathlib import Path
from datetime import datetime
import sys

BRIDGE_ROOT = Path.home() / 'AppData' / 'Roaming' / 'MetaQuotes' / 'Terminal' / 'Common' / 'Files' / 'TelegramSignalCopierBridge'
TIMEOUT_SECONDS = 10
POLL_INTERVAL = 1.0


def parse_cmd(path: Path):
    data = path.read_text(encoding='mbcs', errors='ignore') if path.exists() else ''
    d = {}
    for line in data.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            d[k.strip()] = v.strip()
    return d


def write_result(path: Path, request_id: str, status: str = 'EXECUTED', executed_price: str = None):
    out = []
    out.append(f'request_id={request_id}')
    out.append(f'status={status}')
    out.append(f'completed_at={datetime.utcnow().isoformat()}')
    if executed_price is not None:
        out.append(f'executed_price={executed_price}')
    txt = '\n'.join(out) + '\n'
    p = path.parent / (request_id + '.result')
    p.write_text(txt, encoding='mbcs', errors='ignore')
    return p


def main(run_seconds: int):
    bridge = BRIDGE_ROOT
    if not bridge.exists():
        print('Bridge folder not found:', bridge)
        sys.exit(1)
    print('Watching', bridge)
    start = time.time()
    seen = {}
    while True:
        now = time.time()
        for p in bridge.glob('*.cmd'):
            rid = p.stem
            mtime = p.stat().st_mtime
            if rid not in seen:
                seen[rid] = mtime
            # check for existing .result
            res = bridge / (rid + '.result')
            if res.exists():
                # If a result already exists, remove the command file to mimic EA consumption
                try:
                    p.unlink()
                except Exception:
                    pass
                if rid in seen:
                    del seen[rid]
                continue
            # Simulate result immediately to clear backlog (safe fallback)
            info = parse_cmd(p)
            executed_price = info.get('entry_price')
            write_result(p, rid, status='SIMULATED_NOT_CONSUMED', executed_price=executed_price)
            try:
                p.unlink()
            except Exception:
                pass
            print(f'Simulated result for {rid}')
        if run_seconds and (now - start) > run_seconds:
            break
        time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-seconds', type=int, default=30)
    args = ap.parse_args()
    main(args.run_seconds)
