"""Inspect Telethon _reconnect method fully to understand reconnect failure behavior."""
import inspect
from telethon.network import MTProtoSender

src = inspect.getsource(MTProtoSender._reconnect)
print('=== _reconnect ===')
print(src)
print()
# Find _start_reconnect
src2 = inspect.getsource(MTProtoSender._start_reconnect)
print('=== _start_reconnect ===')
print(src2)
