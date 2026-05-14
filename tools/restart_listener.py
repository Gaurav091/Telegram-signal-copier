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
    proc = subprocess.Popen(cmd, stdout=fh, stderr=fh)
    fh.write(f"Started PID {proc.pid}\n")
print("Started new listener PID:", proc.pid)
