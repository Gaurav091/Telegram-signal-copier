import subprocess, os, sys
from pathlib import Path

PY = sys.executable
ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "listener-restart.log"
PID_FILE = ROOT / "runtime" / "listener.pid"
LOG.parent.mkdir(parents=True, exist_ok=True)

try:
    pid_text = PID_FILE.read_text(encoding="utf-8").strip()
except FileNotFoundError:
    pid_text = ""
except Exception as e:
    pid_text = ""
    print(f"Failed to read pid file {PID_FILE}: {e}")

if pid_text.isdigit():
    pid = int(pid_text)
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True)
        print(f"Killed PID {pid}")
    except Exception as e:
        print(f"Failed to kill {pid}: {e}")
else:
    print("No listener pid file found; starting a new listener")

# Start new listener
cmd = [PY, "-u", "-m", "telegram_signal_copier.main", "listen"]
with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(f"Starting listener with: {cmd}\n")
# Start attached when interactive; otherwise redirect child stdout/stderr to log
workspace_dir = str(Path(__file__).resolve().parents[1])
if sys.stdout.isatty() and sys.stderr.isatty():
    proc = subprocess.Popen(cmd, cwd=workspace_dir)
else:
    # Running non-interactively (e.g., called by supervisor / log monitor).
    # Use DEVNULL + CREATE_NO_WINDOW so the child process does not inherit any
    # pipe handles from the caller — prevents capture_output callers from hanging.
    CREATE_NO_WINDOW = 0x08000000
    with open(LOG, "a", encoding="utf-8") as fh_tmp:
        fh_tmp.write(f"Starting detached listener with: {cmd}\n")
    proc = subprocess.Popen(
        cmd,
        cwd=workspace_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    with open(LOG, "a", encoding="utf-8") as fh_tmp:
        fh_tmp.write(f"Started PID {proc.pid}\n")
print("Started new listener PID:", proc.pid)
