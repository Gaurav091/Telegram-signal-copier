"""Debug runner: enable Telethon DEBUG logging and faulthandler, capture full traces.

This variant installs a temporary import hook to block the `cryptg` C-extension
so Telethon falls back to the pure-Python implementation. Use when suspecting
cryptg/native crypto causes abrupt process termination.
"""
import sys
import logging
import faulthandler
import traceback
import builtins
from pathlib import Path

# Block `cryptg` import so Telethon doesn't pick the C-extension (debug)
_orig_import = builtins.__import__
def _block_cryptg(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'cryptg' or (isinstance(name, str) and name.startswith('cryptg.')):
        raise ImportError('cryptg import blocked for debugging')
    return _orig_import(name, globals, locals, fromlist, level)
builtins.__import__ = _block_cryptg

# Ensure repo root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

# Import app modules after installing the import hook
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.main import _run_with_restarts, configure_logging

LOG_FILE = ROOT / 'logs' / 'ultra_debug_debug.txt'
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# simple file logger
file_handle = open(str(LOG_FILE), 'a', encoding='utf-8', errors='ignore')

def log(msg: str) -> None:
    file_handle.write(msg + "\n")
    file_handle.flush()

# Monkeypatch os._exit and sys.exit to capture early exits
import os
import atexit
_orig__exit = os._exit
def _logged__exit(code: int) -> None:
    try:
        log(f'os._exit called with code {code}')
    except Exception:
        pass
    _orig__exit(code)
os._exit = _logged__exit

_orig_sys_exit = sys.exit
def _logged_sys_exit(code: int | None = 0) -> None:
    try:
        log(f'sys.exit called with code {code}')
    except Exception:
        pass
    _orig_sys_exit(code)
sys.exit = _logged_sys_exit

@atexit.register
def _on_atexit() -> None:
    try:
        log('atexit handlers running')
    except Exception:
        pass
# Hook unhandled exceptions
def _hook(exc_type, exc_val, exc_tb):
    tb = ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
    log(f'UNHANDLED EXCEPTION: {exc_type.__name__}: {exc_val}\n{tb}')
    sys.__excepthook__(exc_type, exc_val, exc_tb)

sys.excepthook = _hook

log(f'Python {sys.version}')
log(f'Platform: {sys.platform}')

# Enable faulthandler to write to our file
try:
    faulthandler.enable(file=file_handle)
    log('Faulthandler enabled')
except Exception as e:
    log(f'Faulthandler enable failed: {e}')

# Load config and set up logging
config = AppConfig.from_env()
config.ensure_runtime_dirs()
configure_logging(config)

# Set Telethon to DEBUG
logging.getLogger('telethon').setLevel(logging.DEBUG)
logging.getLogger('telethon.network').setLevel(logging.DEBUG)
logging.getLogger('telethon.network.mtprotosender').setLevel(logging.DEBUG)
# Attach our file handle to the root logger as well for extra capture
fh = logging.FileHandler(str(LOG_FILE))
fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
logging.getLogger().addHandler(fh)

log('Starting _run_with_restarts (debug)')

import asyncio

try:
    asyncio.run(_run_with_restarts(config))
    log('asyncio.run returned normally')
except Exception as e:
    log(f'ESCAPED EXCEPTION: {type(e).__name__}: {e}')
    log(''.join(traceback.format_exc()))
finally:
    log('debug runner exiting')
    file_handle.close()
