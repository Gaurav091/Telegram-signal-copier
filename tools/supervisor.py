"""Supervisor to run and restart required background processes.

Starts:
- Telegram listener: `-m telegram_signal_copier.main listen`
- Smart supervisor: `tools/smart_supervisor.py` (monitors + auto-fixes code)
- Bridge autofix daemon: `tools/bridge_autofix_daemon.py --run-seconds 0`
- EA status watcher: `tools/ea_status_watcher.py`
- MT5 log watcher: `tools/mt5_log_watcher.py`

Prints prefixed output and restarts processes on non-zero exit.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import List

PROCS = [
    ("listener",       [sys.executable, "-u", "-m", "telegram_signal_copier.main", "listen"]),
    ("smart_supervisor", [sys.executable, "-u", "tools/smart_supervisor.py", "--interval", "30"]),
    ("bridge_autofix", [sys.executable, "-u", "tools/bridge_autofix_daemon.py", "--run-seconds", "0"]),
    ("ea_status",      [sys.executable, "-u", "tools/ea_status_watcher.py", "--interval", "2"]),
    ("mt5_logs",       [sys.executable, "-u", "tools/mt5_log_watcher.py", "--interval", "5"]),
]


def reader_thread(name: str, stream):
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            print(f"[{name}] {line.rstrip()}")
    except Exception:
        pass


def start_proc(cmd: List[str]):
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)


def supervise(loop_delay: float = 2.0):
    procs = {}
    while True:
        for name, cmd in PROCS:
            if name not in procs or procs[name].poll() is not None:
                if name in procs:
                    rc = procs[name].poll()
                    print(f"Process {name} exited with code {rc}, restarting in {loop_delay}s")
                    # drain any remaining output
                    try:
                        out = procs[name].communicate(timeout=0.5)
                        if out and len(out) > 0:
                            print(out)
                    except Exception:
                        pass
                print(f"Starting {name}: {' '.join(cmd)}")
                p = start_proc(cmd)
                procs[name] = p
                t = threading.Thread(target=reader_thread, args=(name, p.stdout), daemon=True)
                t.start()
        try:
            time.sleep(loop_delay)
        except KeyboardInterrupt:
            print("Supervisor received KeyboardInterrupt, terminating children...")
            for p in procs.values():
                try:
                    p.terminate()
                except Exception:
                    pass
            break


if __name__ == "__main__":
    supervise()
