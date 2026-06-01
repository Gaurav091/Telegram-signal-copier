"""PyInstaller runtime hook: configure pytesseract to use bundled Tesseract when frozen."""
import os
import sys


def _configure_bundled_tesseract() -> None:
    if not getattr(sys, "frozen", False):
        return

    # PyInstaller unpacks _internal next to the exe (one-folder mode)
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return

    tess_exe = os.path.join(meipass, "tesseract", "tesseract.exe")
    if not os.path.exists(tess_exe):
        return

    # Point pytesseract at the bundled binary
    try:
        import pytesseract  # type: ignore
        pytesseract.pytesseract.tesseract_cmd = tess_exe
    except Exception:
        pass

    # Tell Tesseract where its own tessdata is
    tessdata = os.path.join(meipass, "tesseract", "tessdata")
    if os.path.isdir(tessdata):
        os.environ.setdefault("TESSDATA_PREFIX", tessdata)

    # Add the tesseract folder to PATH so its DLL dependencies resolve
    tess_dir = os.path.dirname(tess_exe)
    current_path = os.environ.get("PATH", "")
    if tess_dir not in current_path:
        os.environ["PATH"] = tess_dir + os.pathsep + current_path


_configure_bundled_tesseract()
