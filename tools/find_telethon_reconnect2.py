"""Find Telethon files with 'connecting failed' text."""
import pathlib
import telethon

root = pathlib.Path(telethon.__file__).parent
for f in root.rglob('*.py'):
    try:
        text = f.read_text(encoding='utf-8', errors='ignore')
        if 'connecting failed' in text.lower() or 'Attempt' in text:
            print(f.relative_to(root))
            idx = text.lower().find('connecting failed')
            if idx >= 0:
                print('  ', text[max(0, idx-80):idx+80])
            idx2 = text.find('Attempt')
            if idx2 >= 0:
                print('  Attempt context:', text[max(0, idx2-20):idx2+120])
    except Exception:
        pass
