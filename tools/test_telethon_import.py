import sys
try:
    import telethon
    print('telethon', getattr(telethon, '__version__', 'unknown'))
except Exception as e:
    print('IMPORT ERROR:', type(e).__name__, e)
    raise
finally:
    sys.stdout.flush()
