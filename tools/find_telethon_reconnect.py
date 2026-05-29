"""Find Telethon code that logs 'connecting failed' warning."""
import pathlib
import re
import telethon

root = pathlib.Path(telethon.__file__).parent
pattern = re.compile(r'.{0,40}(connecting|reconnect|attempt).{0,40}', re.IGNORECASE)
for f in root.rglob('*.py'):
    try:
        text = f.read_text(encoding='utf-8', errors='ignore')
        for m in pattern.findall(text):
            if 'failed' in m.lower() or 'warning' in m.lower():
                print(f'{f.name}: {m.strip()}')
    except Exception:
        pass
