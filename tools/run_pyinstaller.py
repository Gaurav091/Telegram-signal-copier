"""Run PyInstaller and capture all output to a log file."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "pyinstaller_run.txt"

cmd = [
    sys.executable, "-m", "PyInstaller",
    "packaging/TelegramSignalCopier.spec",
    "--distpath", "dist",
    "--workpath", "build/pyinstaller",
    "--noconfirm",
    "--clean",
]

print(f"Running: {' '.join(cmd)}")
print(f"CWD: {ROOT}")
print(f"Log: {LOG}")

result = subprocess.run(
    cmd,
    cwd=str(ROOT),
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)

output = result.stdout + "\n\n--- STDERR ---\n" + result.stderr
LOG.write_text(output, encoding="utf-8")

print(f"Exit code: {result.returncode}")
print("--- Last 30 lines of output ---")
lines = output.splitlines()
for line in lines[-30:]:
    print(line)
