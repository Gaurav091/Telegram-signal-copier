#!/usr/bin/env python3
import sys,os,re
base=r'C:\Users\HP\AppData\Roaming\MetaQuotes\Terminal\53785E099C927DB68A545C249CDBCE06\logs'
patterns = sys.argv[1:]
if not patterns:
    print('Usage: search_mt5_logs.py <pattern> [pattern2 ...]')
    sys.exit(1)
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
        for p in patterns:
            if p in data:
                print(f'{path}: contains {p}')
                for m in re.finditer(re.escape(p), data):
                    start = max(0, m.start() - 200)
                    end = min(len(data), m.end() + 200)
                    snippet = data[start:end].replace('\r\n','\\n').replace('\n','\\n')
                    print('...'+snippet+'...')
                    break
