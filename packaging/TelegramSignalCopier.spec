# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


SPEC_DIR = Path(globals().get("SPECPATH", Path.cwd() / "packaging")).resolve()
ROOT = SPEC_DIR.parent

# ── Venv site-packages (for manual data collection) ──────────────────────────
import glob as _glob

def _site_data(pkg: str, *patterns: str) -> list[tuple[str, str]]:
    """Collect data files from a venv package without importing it."""
    base = ROOT / ".venv" / "Lib" / "site-packages" / pkg
    result = []
    for pat in patterns:
        for f in base.glob(pat):
            rel = f.parent.relative_to(ROOT / ".venv" / "Lib" / "site-packages")
            result.append((str(f), str(rel).replace("\\", "/")))
    return result

datas = [
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "mt5" / "Experts" / "TelegramSignalCopierEA.mq5"), "mt5/Experts"),
]

# Bundle portable Tesseract (no separate install needed on target machine)
_tess_portable = SPEC_DIR / "tesseract-portable"
if _tess_portable.exists():
    datas += [
        (str(_tess_portable / "tesseract.exe"), "tesseract"),
        (str(_tess_portable / "libtesseract-5.dll"), "tesseract"),
        (str(_tess_portable / "tessdata"), "tesseract/tessdata"),
    ]
    # Include all DLLs from the portable folder
    for _dll in _tess_portable.glob("*.dll"):
        datas += [(str(_dll), "tesseract")]

# Telethon has no non-Python data files — nothing to include
# PIL / Pillow data files
datas += _site_data("PIL", "*.dat", "*.txt")

hiddenimports = [
    # Telethon — only the submodules actually needed at runtime
    "telethon.crypto",
    "telethon.crypto.authkey",
    "telethon.crypto.rsa",
    "telethon.network",
    "telethon.network.connection",
    "telethon.network.connection.tcpabridged",
    "telethon.network.connection.tcpfull",
    "telethon.network.connection.tcpintermediate",
    "telethon.network.connection.tcpmtproxy",
    "telethon.network.connection.tcpobfuscated",
    "telethon.network.mtprotosender",
    "telethon.network.authenticator",
    "telethon.sessions",
    "telethon.sessions.sqlite",
    "telethon.sessions.memory",
    "telethon.tl",
    "telethon.tl.functions",
    "telethon.tl.types",
    "telethon.tl.patched",
    "telethon.events",
    "telethon.events.newmessage",
    "telethon.events.album",
    "telethon.extensions",
    "telethon.extensions.html",
    "telethon.extensions.markdown",
    # pytesseract
    "pytesseract",
    # GUI
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "flet",
    "telegram_signal_copier.gui",
    # cryptography used by telethon
    "cryptg",
]


a = Analysis(
    [str(ROOT / "src" / "telegram_signal_copier" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPEC_DIR / "hook_tesseract_bundled.py")],
    excludes=[
        # These hang during PyInstaller's module-analysis phase on this machine
        # (SSL handshake stalls). They're available at runtime via the venv/system.
        "win32com",
        "win32api",
        "_ssl",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TelegramSignalCopier",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TelegramSignalCopier",
)