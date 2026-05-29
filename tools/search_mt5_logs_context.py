#!/usr/bin/env python3
import sys,os,re
base=r'C:\Users\HP\AppData\Roaming\MetaQuotes\Terminal\53785E099C927DB68A545C249CDBCE06\logs'
if len(sys.argv) < 2:
    print('Usage: search_mt5_logs_context.py <pattern> [context_chars]')
    sys.exit(1)
pattern = sys.argv[1]
ctx = int(sys.argv[2]) if len(sys.argv) >= 3 else 800
for root, dirs, files in os.walk(base):
    for fname in files:
        path = os.path.join(root, fname)
        try:
            with open(path, 'rb') as fh:
                raw = fh.read()
            try:
                data = raw.decode('utf-16')
            except Exception:
                try:
                    data = raw.decode('utf-8', errors='ignore')
                except Exception:
                    continue
        except Exception:
            continue
        for m in re.finditer(re.escape(pattern), data):
            start = max(0, m.start() - ctx)
            end = min(len(data), m.end() + ctx)
            snippet = data[start:end]
            print('FILE:', path)
            print('--- CONTEXT START ---')
            print(snippet)
            print('--- CONTEXT END ---\n')
            break
