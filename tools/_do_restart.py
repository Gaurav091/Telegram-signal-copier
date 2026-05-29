import subprocess, sys
from pathlib import Path
ROOT = Path(r"d:\Github repos\Telegram signal Copier")
pid_file = ROOT / "runtime" / "listener.pid"
if pid_file.exists():
    old = pid_file.read_text().strip()
    if old.isdigit():
        subprocess.run(["taskkill", "/PID", old, "/F"], capture_output=True)
        print("Killed old PID", old)
log_path = ROOT / "logs" / "listener-restart.log"
log = open(log_path, "a", encoding="utf-8")
cmd = [sys.executable, "-u", "-m", "telegram_signal_copier.main", "listen"]
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
env = {"PYTHONPATH": str(ROOT / "src")}
import os
full_env = {**os.environ, **env}
proc = subprocess.Popen(
    cmd, cwd=str(ROOT), stdout=log, stderr=log,
    creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
    env=full_env,
)
pid_file.write_text(str(proc.pid))
print("Listener started PID:", proc.pid)
