"""Show the full _connect method in MTProtoSender."""
import inspect
from telethon.network import MTProtoSender

src = inspect.getsource(MTProtoSender._connect)
print('=== _connect ===')
print(src)
