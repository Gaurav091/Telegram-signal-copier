import subprocess, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(VENV_PY if VENV_PY.exists() else Path(sys.executable))
LOG = ROOT / "logs" / "listener-restart.log"
PID_FILE = ROOT / "runtime" / "listener.pid"
LOG.parent.mkdir(parents=True, exist_ok=True)
PID_FILE.parent.mkdir(parents=True, exist_ok=True)


def _write_pid(pid: int) -> None:
    PID_FILE.write_text(f"{pid}\n", encoding="utf-8")


def _workspace_listener_pids() -> list[int]:
    workspace_marker = ROOT.name.replace("'", "''")
    ps_cmd = (
        "Get-CimInstance Win32_Process"
        " | Where-Object { $PSItem.CommandLine -and $PSItem.Name -match 'python'"
        " -and $PSItem.CommandLine -match 'telegram_signal_copier\\.main\\s+listen'"
        " -and $PSItem.CommandLine -match '"
        + workspace_marker
        + "' }"
        " | ForEach-Object { [string]$PSItem.ProcessId }"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return []

    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _taskkill_pid(pid: int) -> tuple[bool, str]:
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    output = "\n".join(part for part in (stdout, stderr) if part)
    if result.returncode == 0:
        return True, output
    # taskkill returns non-zero when PID does not exist; treat as benign stale PID.
    not_found_markers = (
        "not found",
        "no running instance",
        "cannot find the process",
    )
    lower_output = output.lower()
    if any(marker in lower_output for marker in not_found_markers):
        return False, "not_found"
    return False, output or f"taskkill exit code {result.returncode}"

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
        killed, message = _taskkill_pid(pid)
        if killed:
            print(f"Killed PID {pid}")
        elif message == "not_found":
            print(f"PID {pid} already stopped; continuing")
        else:
            print(f"Failed to kill {pid}: {message}")
    except Exception as e:
        print(f"Failed to kill {pid}: {e}")
else:
    print("No listener pid file found; starting a new listener")

# Also kill any listener process in this workspace discovered by command-line.
for existing_pid in _workspace_listener_pids():
    if existing_pid == os.getpid():
        continue
    try:
        killed, message = _taskkill_pid(existing_pid)
        if killed:
            print(f"Killed listener PID {existing_pid}")
        elif message == "not_found":
            pass
        else:
            print(f"Failed to kill listener PID {existing_pid}: {message}")
    except Exception as e:
        print(f"Failed to kill listener PID {existing_pid}: {e}")

for stale in (PID_FILE, ROOT / "runtime" / "listener.lock"):
    try:
        stale.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass

# Start new listener
cmd = [PY, "-u", "-m", "telegram_signal_copier.main", "listen"]
with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(f"Starting listener with: {cmd}\n")
# Keep the listener in the current terminal when launched interactively.
workspace_dir = str(Path(__file__).resolve().parents[1])
if sys.stdout.isatty() and sys.stderr.isatty():
    proc = subprocess.Popen(cmd, cwd=workspace_dir)
    _write_pid(proc.pid)
    print("Started new listener PID:", proc.pid)
    raise SystemExit(proc.wait())
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
    _write_pid(proc.pid)
    with open(LOG, "a", encoding="utf-8") as fh_tmp:
        fh_tmp.write(f"Started PID {proc.pid}\n")
print("Started new listener PID:", proc.pid)
