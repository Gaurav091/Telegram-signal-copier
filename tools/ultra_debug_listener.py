"""Ultra-minimal listener test: run _run_with_restarts for 60s and log everything."""
import sys, asyncio, traceback, os, time
from pathlib import Path

# Patch stderr to also go to a file
LOG_FILE = Path(__file__).parent.parent / 'logs' / 'ultra_debug.txt'
LOG_FILE.parent.mkdir(exist_ok=True)
_lf = open(str(LOG_FILE), 'w', encoding='utf-8', errors='ignore')

class Tee:
    def __init__(self, *streams): self._s = streams
    def write(self, d):
        for s in self._s:
            try: s.write(d)
            except: pass
    def flush(self):
        for s in self._s:
            try: s.flush()
            except: pass
    def fileno(self): return self._s[0].fileno()

sys.stdout = Tee(sys.__stdout__, _lf)
sys.stderr = Tee(sys.__stderr__, _lf)

def _hook(exc_type, exc_val, exc_tb):
    msg = f'UNHANDLED: {exc_type.__name__}: {exc_val}\n{"".join(traceback.format_tb(exc_tb))}'
    _lf.write(msg); _lf.flush()
    sys.__excepthook__(exc_type, exc_val, exc_tb)

sys.excepthook = _hook

print(f'Python {sys.version}', flush=True)
print(f'Platform: {sys.platform}', flush=True)

# Add src to path
src = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(src))

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.main import _run_with_restarts, configure_logging

config = AppConfig.from_env()
config.ensure_runtime_dirs()
configure_logging(config)

print('Config loaded. About to asyncio.run(_run_with_restarts)...', flush=True)

try:
    asyncio.run(_run_with_restarts(config))
    print('asyncio.run returned normally', flush=True)
except KeyboardInterrupt:
    print('KeyboardInterrupt', flush=True)
except SystemExit as e:
    print(f'SystemExit({e.code})', flush=True)
except BaseException as e:
    print(f'ESCAPED BaseException: {type(e).__name__}: {e}', flush=True)
    traceback.print_exc()
finally:
    print('Script ending', flush=True)
    _lf.close()
