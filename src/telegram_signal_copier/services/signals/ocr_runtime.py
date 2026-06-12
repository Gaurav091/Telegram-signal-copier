"""Runtime helpers for bundled Tesseract OCR.

PyInstaller one-folder builds place resources under ``sys._MEIPASS`` (usually
``<install>\\_internal``).  Some modules historically hardcoded
``C:\\Program Files\\Tesseract-OCR\\tesseract.exe``; this module centralizes frozen
resource lookup so the bundled Tesseract is used before falling back to a normal
system install.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def _meipass_paths() -> list[Path]:
    if not getattr(sys, "frozen", False):
        return []

    raw = getattr(sys, "_MEIPASS", None)
    paths: list[Path] = []
    if raw:
        paths.append(Path(raw))

    try:
        exe_dir = Path(sys.executable).resolve().parent
    except Exception:
        exe_dir = Path.cwd()

    paths.extend(
        [
            exe_dir / "_internal",
            exe_dir,
        ]
    )

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(resolved)
    return deduped


def bundled_tesseract_path() -> Path | None:
    """Return the bundled ``tesseract.exe`` path when available."""
    candidates: list[Path] = []
    for root in _meipass_paths():
        candidates.extend(
            [
                root / "tesseract" / "tesseract.exe",
                root / "tesseract.exe",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def bundled_tessdata_path() -> Path | None:
    tesseract = bundled_tesseract_path()
    if tesseract is None:
        return None
    candidate = tesseract.parent / "tessdata"
    return candidate if candidate.is_dir() else None


def standard_tesseract_path() -> Path | None:
    for candidate in (
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ):
        if candidate.exists():
            return candidate
    return None


def tesseract_path() -> Path | None:
    return bundled_tesseract_path() or standard_tesseract_path()


def configure_pytesseract(pytesseract: Any | None = None) -> Path | None:
    """Configure ``pytesseract`` to use the bundled or installed Tesseract.

    Returns the configured executable path, or ``None`` when no binary is usable.
    """
    path = tesseract_path()
    if path is None:
        return None

    try:
        if pytesseract is None:
            import pytesseract  # type: ignore
        else:
            globals()["pytesseract"] = pytesseract  # noqa: F841
        pytesseract.pytesseract.tesseract_cmd = str(path)
        try:
            pytesseract.tesseract_cmd = str(path)
        except Exception:
            pass
    except Exception:
        return None

    tessdata = path.parent / "tessdata"
    if tessdata.is_dir():
        os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))

    tess_dir = str(path.parent)
    current_path = os.environ.get("PATH", "")
    if current_path != tess_dir and not current_path.startswith(tess_dir + os.pathsep):
        os.environ["PATH"] = tess_dir + os.pathsep + current_path

    return path
