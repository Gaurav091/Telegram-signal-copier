"""Show _try_connect in MTProtoSender."""
import inspect
from telethon.network import MTProtoSender

src = inspect.getsource(MTProtoSender._try_connect)
print('=== _try_connect ===')
print(src)
