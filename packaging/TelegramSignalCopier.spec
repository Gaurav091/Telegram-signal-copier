# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


SPEC_DIR = Path(globals().get("SPECPATH", Path.cwd() / "packaging")).resolve()
ROOT = SPEC_DIR.parent

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

datas += collect_data_files("telethon")
datas += collect_data_files("pytesseract")
datas += collect_data_files("PIL")

hiddenimports = []
hiddenimports += collect_submodules("telethon")
hiddenimports += collect_submodules("pytesseract")


a = Analysis(
    [str(ROOT / "src" / "telegram_signal_copier" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPEC_DIR / "hook_tesseract_bundled.py")],
    excludes=[],
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