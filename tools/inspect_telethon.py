"""Inspect Telethon MTProtoSender reconnect/disconnect logic."""
import inspect
from telethon.network import MTProtoSender

# Print all method names
methods = [m for m in dir(MTProtoSender) if 'reconnect' in m.lower() or 'disconnect' in m.lower() or 'cancel' in m.lower() or 'error' in m.lower()]
print('Methods:', methods)

for m in methods:
    try:
        src = inspect.getsource(getattr(MTProtoSender, m))
        print(f'\n=== {m} ===')
        print(src[:600])
    except Exception as e:
        print(f'{m}: {e}')
