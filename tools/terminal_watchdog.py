#!/usr/bin/env python3
"""
Terminal watchdog for the project.
- Scans Python processes launched from this workspace.
- Optionally kills non-relevant Python processes (autoclean).
- Restarts listener and supervisor if missing.
- Can run once (`--once`) or as a daemon (`--daemon`).

Safety: only targets `python*` processes whose command-line contains the workspace path.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import os
from pathlib import Path
import logging

WORKSPACE = Path(__file__).resolve().parents[1]
LOG_DIR = WORKSPACE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = LOG_DIR / "terminal_watchdog.log"

logging.basicConfig(filename=LOG, level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")

# Patterns considered relevant (kept running)
DEFAULT_ALLOWED = [
    "-m telegram_signal_copier listen",
    "telegram_signal_copier.main",
    "-m telegram_signal_copier.main",
    "workflow_supervisor.py",
    "supervisor_start.py",
    "restart_listener.py",
    "terminal_watchdog.py",
    "log_monitor_agent.py",
    "telegram_signal_copier\\main",
    "telegram_signal_copier/main",
    "telegram_signal_copier.main",
]

# Extra substrings that should always be treated as relevant (defensive)
EXTRA_KEEP_SUBSTRS = [
    "log_monitor_agent.py",
]

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _ps_all_process_map() -> dict:
    """Return a mapping of PID -> ParentPID for all system processes."""
    ps_cmd = (
        "Get-CimInstance Win32_Process | ForEach-Object { [string]$PSItem.ProcessId + '|' + [string]$PSItem.ParentProcessId }"
    )
    try:
        out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps_cmd], stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        return {}
    mapping: dict[int, int] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        left, sep, right = line.partition("|")
        try:
            pid = int(left.strip())
            ppid = int(right.strip())
        except Exception:
            continue
        mapping[pid] = ppid
    return mapping


def _ps_workspace_python_processes() -> list[dict]:
    """Return list of dicts: {'pid': int, 'ppid': int, 'cmd': str} for python processes whose commandline contains workspace path."""
    ws_marker = WORKSPACE.name.replace("'", "''")  # escape single quotes for PS
    ps_cmd = (
        "Get-CimInstance Win32_Process"
        " | Where-Object { $PSItem.CommandLine -and $PSItem.CommandLine -match '"
        + ws_marker
        + "' -and $PSItem.Name -match 'python' }"
        " | ForEach-Object { [string]$PSItem.ProcessId + '|' + [string]$PSItem.ParentProcessId + '|' + $PSItem.CommandLine }"
    )
    try:
        out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps_cmd], stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        return []
    procs = []
    for line in out.splitlines():
        if not line.strip():
            continue
        # expected format: PID|PPID|COMMANDLINE
        first, sep, rest = line.partition("|")
        second, sep2, cmd = rest.partition("|")
        try:
            pid = int(first.strip())
            ppid = int(second.strip())
        except Exception:
            continue
        procs.append({"pid": pid, "ppid": ppid, "cmd": cmd.strip()})
    return procs


def _ps_workspace_shell_processes() -> list[dict]:
    """Return list of dicts: {'pid': int, 'cmd': str} for shell processes (powershell/pwsh/cmd) whose commandline contains workspace path."""
    ws_marker = WORKSPACE.name.replace("'", "''")
    ps_cmd = (
        "Get-CimInstance Win32_Process"
        " | Where-Object { $PSItem.CommandLine -and $PSItem.CommandLine -match '"
        + ws_marker
        + "' -and ($PSItem.Name -match 'powershell' -or $PSItem.Name -match 'pwsh' -or $PSItem.Name -match 'cmd') }"
        " | ForEach-Object { [string]$PSItem.ProcessId + '|' + $PSItem.CommandLine }"
    )
    try:
        out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps_cmd], stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        return []
    procs = []
    for line in out.splitlines():
        if not line.strip():
            continue
        pid_str, sep, cmd = line.partition("|")
        try:
            pid = int(pid_str.strip())
        except Exception:
            continue
        procs.append({"pid": pid, "cmd": cmd.strip()})
    return procs


def _is_relevant(cmd: str, allowed: list[str]) -> bool:
    cl = cmd.lower()
    for a in allowed:
        if a.lower() in cl:
            return True
    return False


def _kill_pid(pid: int) -> bool:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info("Killed PID %d", pid)
        return True
    except Exception as e:
        logging.warning("Failed to kill PID %d: %s", pid, e)
        return False


def _dedupe_processes(procs: list[dict], marker: str) -> None:
    matched = [p for p in procs if marker.lower() in p["cmd"].lower()]
    if len(matched) <= 1:
        return
    matched = sorted(matched, key=lambda x: x["pid"], reverse=True)
    keep = matched[0]
    logging.info("Dedup marker=%s keep pid=%d kill=%s", marker, keep["pid"], [m["pid"] for m in matched[1:]])
    print(f"Dedup {marker}: keep PID={keep['pid']} kill {[m['pid'] for m in matched[1:]]}")
    for p in matched[1:]:
        _kill_pid(p["pid"])


def _restart_listener():
    script = WORKSPACE / "tools" / "restart_listener.py"
    if not script.exists():
        logging.warning("restart_listener.py missing; cannot restart listener")
        return False
    try:
        subprocess.run([sys.executable, str(script)], check=False)
        logging.info("Invoked restart_listener.py")
        return True
    except Exception as e:
        logging.warning("Failed to invoke restart_listener.py: %s", e)
        return False


def _start_supervisor(interval=8, no_autofix=True):
    script = WORKSPACE / "tools" / "workflow_supervisor.py"
    if not script.exists():
        logging.warning("workflow_supervisor.py missing; cannot start supervisor")
        return False
    cmd = [sys.executable, str(script), "--interval", str(interval)]
    if no_autofix:
        cmd.append("--no-autofix")
    try:
        # Start attached to the invoking terminal (no detached creation flags)
        proc = subprocess.Popen(cmd, cwd=str(WORKSPACE))
        logging.info("Started supervisor PID %d", proc.pid)
        print(f"Started supervisor PID: {proc.pid}")
        return True
    except Exception as e:
        logging.warning("Failed to start supervisor: %s", e)
        return False


def run_once(autoclean: bool, restart_listener_flag: bool, restart_supervisor_flag: bool, close_shells: bool = False, allowed=None):
    allowed = allowed or DEFAULT_ALLOWED
    current_pid = os.getpid()
    procs = [p for p in _ps_workspace_python_processes() if p["pid"] != current_pid]
    print(f"Found {len(procs)} workspace Python process(es)")
    logging.info("Found %d workspace Python process(es)", len(procs))

    # Treat some filenames defensively as always-relevant to avoid accidental kills
    extra_keep = [s.lower() for s in EXTRA_KEEP_SUBSTRS]
    relevant = [p for p in procs if _is_relevant(p["cmd"], allowed) or any(s in p["cmd"].lower() for s in extra_keep)]
    non_rel = [p for p in procs if not (_is_relevant(p["cmd"], allowed) or any(s in p["cmd"].lower() for s in extra_keep))]

    print(f"Relevant: {len(relevant)}  Non-relevant: {len(non_rel)}")
    for p in relevant:
        print(f"  KEEP PID={p['pid']} CMD={p['cmd'][:180]}")
        logging.info("KEEP PID=%d CMD=%s", p["pid"], p["cmd"])

    if autoclean and non_rel:
        print("Killing non-relevant python processes:")
        for p in non_rel:
            print(f"  KILL PID={p['pid']} CMD={p['cmd'][:180]}")
            _kill_pid(p["pid"])
    else:
        for p in non_rel:
            print(f"  IGNORED PID={p['pid']} CMD={p['cmd'][:180]}")

    # Optionally close non-relevant shell terminals (PowerShell/pwsh/cmd)
    if close_shells:
        parent_pid = os.getppid()
        py_procs = _ps_workspace_python_processes()
        ppid_map = _ps_all_process_map()
        extra_keep = [s.lower() for s in EXTRA_KEEP_SUBSTRS]
        # collect python PIDs that are considered relevant
        relevant_python_pids = [p["pid"] for p in py_procs if _is_relevant(p.get("cmd", ""), allowed) or any(s in p.get("cmd", "").lower() for s in extra_keep)]
        shells = [s for s in _ps_workspace_shell_processes() if s["pid"] not in (current_pid, parent_pid)]
        non_rel_shells = []
        for s in shells:
            cmd = s["cmd"]
            pid = s["pid"]
            # keep if the shell itself looks relevant
            if _is_relevant(cmd, allowed):
                print(f"  KEEP shell PID={pid} CMD={cmd[:160]}")
                continue

            # check whether any relevant python process has this shell as an ancestor
            def _has_ancestor(child_pid: int, ancestor_pid: int) -> bool:
                cur = child_pid
                seen: set[int] = set()
                while True:
                    parent = ppid_map.get(cur)
                    if parent is None or parent == 0 or parent in seen or parent == cur:
                        return False
                    if parent == ancestor_pid:
                        return True
                    seen.add(parent)
                    cur = parent

            keep_shell = False
            for rp in relevant_python_pids:
                if _has_ancestor(rp, pid):
                    keep_shell = True
                    break

            if keep_shell:
                print(f"  KEEP shell PID={pid} (ancestor host of relevant python pid)")
                continue

            non_rel_shells.append(s)

        if non_rel_shells:
            print("Closing non-relevant shell terminals:")
            for s in non_rel_shells:
                print(f"  CLOSE PID={s['pid']} CMD={s['cmd'][:160]}")
                _kill_pid(s["pid"])    

    # Ensure listener
    procs_after = _ps_workspace_python_processes()
    _dedupe_processes(procs_after, "-m telegram_signal_copier.main listen")
    _dedupe_processes(procs_after, "workflow_supervisor.py")
    procs_after = _ps_workspace_python_processes()
    cmds = "\n".join(p["cmd"].lower() for p in procs_after)
    has_listener = any(
        ("-m telegram_signal_copier listen" in c)
        or ("telegram_signal_copier.main" in c)
        or ("-m telegram_signal_copier.main" in c)
        for c in cmds.splitlines()
    )
    has_supervisor = any("workflow_supervisor.py" in c for c in cmds.splitlines())

    if not has_listener and restart_listener_flag:
        print("Listener not running — restarting via restart_listener.py")
        logging.info("Listener not running — invoking restart")
        _restart_listener()
    else:
        print("Listener running")

    if not has_supervisor and restart_supervisor_flag:
        print("Supervisor not running — starting supervisor (attached) --- no-autofix")
        logging.info("Supervisor not running — starting supervisor")
        _start_supervisor()
    else:
        print("Supervisor running")


def daemon_loop(interval: int, autoclean: bool, restart_listener_flag: bool, restart_supervisor_flag: bool, close_shells: bool = False, allowed=None):
    allowed = allowed or DEFAULT_ALLOWED
    logging.info("Starting terminal_watchdog daemon: interval=%ds autoclean=%s restart_listener=%s restart_supervisor=%s close_shells=%s", interval, autoclean, restart_listener_flag, restart_supervisor_flag, close_shells)
    try:
        while True:
            run_once(autoclean, restart_listener_flag, restart_supervisor_flag, close_shells=close_shells, allowed=allowed)
            time.sleep(interval)
    except KeyboardInterrupt:
        logging.info("terminal_watchdog daemon stopped by KeyboardInterrupt")
        print("Stopped terminal_watchdog")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true', help='Run a single pass and exit')
    ap.add_argument('--daemon', action='store_true', help='Run as daemon')
    ap.add_argument('--interval', type=int, default=60, help='Daemon interval seconds')
    ap.add_argument('--no-autoclean', dest='autoclean', action='store_false', help='Do not kill non-relevant processes')
    ap.add_argument('--no-restart-listener', dest='restart_listener', action='store_false', help='Do not restart listener')
    ap.add_argument('--no-restart-supervisor', dest='restart_supervisor', action='store_false', help='Do not start supervisor')
    ap.add_argument('--close-shells', dest='close_shells', action='store_true', help='Close non-relevant shell processes (PowerShell/cmd) whose commandlines contain the workspace path')
    args = ap.parse_args()

    if args.once and args.daemon:
        print('Cannot use --once and --daemon together')
        sys.exit(2)

    if args.once:
        run_once(autoclean=args.autoclean, restart_listener_flag=args.restart_listener, restart_supervisor_flag=args.restart_supervisor, close_shells=args.close_shells)
        sys.exit(0)

    if args.daemon:
        daemon_loop(args.interval, autoclean=args.autoclean, restart_listener_flag=args.restart_listener, restart_supervisor_flag=args.restart_supervisor, close_shells=args.close_shells)
