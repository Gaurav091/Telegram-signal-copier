#!/usr/bin/env python3
import os
from pathlib import Path
import sys

root = Path(os.environ.get('APPDATA','')) / 'MetaQuotes' / 'Terminal'
if not root.exists():
    print('Terminal root missing:', root)
    sys.exit(1)

matches = []
for dirpath, dirnames, filenames in os.walk(root):
    for fn in filenames:
        if fn.lower().endswith('.log') or fn.lower().endswith('.txt'):
            p = Path(dirpath) / fn
            try:
                data = p.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            if 'TelegramSignalCopierEA' in data or 'inbox/*.cmd' in data or 'TelegramSignalCopierBridge' in data:
                matches.append((p, data.count('TelegramSignalCopierEA')))

if not matches:
    print('No matching logs found')
    sys.exit(0)

for p, cnt in sorted(matches, key=lambda x: x[1], reverse=True)[:20]:
    print(p)
    try:
        snippet = '\n'.join([l for l in p.read_text(encoding='utf-8', errors='ignore').splitlines() if 'TelegramSignalCopierEA' in l or 'inbox/*.cmd' in l or 'TelegramSignalCopierBridge' in l][-20:])
        print(snippet)
    except Exception:
        pass
    print('---')
