keep = ('INFO', 'ERROR', 'WARNING', 'Resolved', 'FAILED', '30s', 'Disconnected', 'client.start', 'run_until')
lines = [l for l in open('logs/full_listener_diag.txt', encoding='utf-8', errors='ignore') if any(k in l for k in keep)]
print(''.join(lines))
