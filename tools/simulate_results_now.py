from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ExecutionResult


def main():
    config = AppConfig.from_env()
    bridge = Path(config.bridge_inbox_dir)
    if not bridge.exists():
        print('Bridge folder not found:', bridge)
        return
    processed = []
    for p in sorted(bridge.glob('*.cmd')):
        rid = p.stem
        res = bridge / (rid + '.result')
        if res.exists():
            print(f'SKIP {rid}: result exists')
            continue
        try:
            text = p.read_text(encoding='mbcs', errors='ignore')
        except Exception:
            text = p.read_text(encoding='utf-8', errors='ignore')
        values = {}
        for line in text.splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip()
        entry_price = values.get('entry_price')
        out_lines = [f'request_id={rid}', 'status=SIMULATED_NOT_CONSUMED', f'completed_at={datetime.now(timezone.utc).isoformat()}']
        if entry_price:
            out_lines.append(f'executed_price={entry_price}')
        out_text = '\n'.join(out_lines) + '\n'
        try:
            res.write_text(out_text, encoding='mbcs', errors='ignore')
        except Exception:
            res.write_text(out_text, encoding='utf-8', errors='ignore')
        parsed = ExecutionResult.from_bridge_lines(out_text.splitlines())
        print(f'WROTE {res.name}: status={parsed.status} executed_price={parsed.executed_price}')
        processed.append(rid)
    print(f'DONE, processed={len(processed)}')


if __name__ == '__main__':
    main()
