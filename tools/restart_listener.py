import subprocess, os, sys
from pathlib import Path

PY = sys.executable
LOG = Path(__file__).resolve().parents[1] / "logs" / "listener-restart.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

ps_cmd = "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'telegram_signal_copier.main' } | Select-Object -ExpandProperty ProcessId"
try:
    out = subprocess.check_output(["powershell", "-Command", ps_cmd], stderr=subprocess.DEVNULL, text=True)
except subprocess.CalledProcessError:
    out = ""

pids = [int(x.strip()) for x in out.splitlines() if x.strip().isdigit()]
for pid in pids:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True)
        print(f"Killed PID {pid}")
    except Exception as e:
        print(f"Failed to kill {pid}: {e}")

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
