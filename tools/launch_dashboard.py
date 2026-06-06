"""Launches the Flet dashboard in a detached window with no console.
The Flet engine spawns its own desktop window, so we just need to start
the Python process in the background and let it open the GUI window.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

if __name__ == "__main__":
    kwargs = {
        "cwd": str(ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        # Detach completely from the current console so no cmd window appears.
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NO_WINDOW

    subprocess.Popen(
        [str(VENV_PY), "-m", "telegram_signal_copier.main", "dashboard"],
        **kwargs,
    )
    print("Dashboard launched in a detached window.")
