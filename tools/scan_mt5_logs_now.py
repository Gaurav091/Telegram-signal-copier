from pathlib import Path
import os
import sys

KEYWORDS = [
    "TelegramSignalCopierEA",
    "TelegramSignalCopierBridge",
    "inbox/*.cmd",
    "ProcessBridge",
    "ReadTrade",
    "WriteResult",
    "NOT_CONSUMED",
]

root = Path(os.getenv('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'MetaQuotes' / 'Terminal'
if not root.exists():
    print('Terminal root not found:', root)
    sys.exit(0)

matches = []
for term in root.iterdir():
    p_logs = term / 'MQL5' / 'Logs'
    if not p_logs.exists():
        p_logs = term / 'MQL4' / 'Logs'
    if not p_logs.exists():
        continue
    for f in p_logs.rglob('*.log'):
        try:
            data = f.read_bytes().decode('utf-8', errors='ignore')
        except Exception:
            continue
        hits = []
        for line in data.splitlines():
            if any(k in line for k in KEYWORDS):
                hits.append(line)
        if hits:
            matches.append((f, hits[-20:]))

if not matches:
    print('No matching MT5 log entries found')
    sys.exit(0)

for f, snippet in matches:
    print('---', f)
    for l in snippet:
        print(l)
    print()
