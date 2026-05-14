#!/usr/bin/env python
"""
Workflow Supervisor Startup Wrapper

Runs the autonomous supervisor agent with auto-restart enabled by default.
Logs all output to daily workflow_supervisor_<date>.jsonl in logs/ folder.

Usage:
    python tools/supervisor_start.py              # autofix ON (default)
    python tools/supervisor_start.py --no-autofix # no auto-restart
    python tools/supervisor_start.py --help       # show all options
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start autonomous workflow supervisor with optional auto-restart",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
WORKFLOW SUPERVISOR MONITORS:
  Telegram → Incoming message receipt, listener health
  Parser   → Signal extraction, AI success/failure, decision (APPROVED/REJECTED)
  Bridge   → Command queue health, MT5 consumption speed
  MT5 EA   → Heartbeat, execution status, filled trades

OUTPUT VERDICTS:
  HEALTHY    - All components alive, no issues
  DEGRADED   - Issue detected (idle timeout, AI failures, old message)
  BLOCKED    - Critical: EA offline, stale commands, listener down
  RECOVERING - Was broken, recovering within stability window

AUTO-FIX ACTIONS (when --autofix is ON):
  - Restart listener if stale or not receiving messages
  - Clean up old stale temp files from bridge

LOG FILES:
  logs/workflow_supervisor_YYYY-MM-DD.jsonl  - Daily JSON event log
  logs/workflow_supervisor_actions.log       - Auto-fix actions taken
  logs/bridge_health_YYYY-MM-DD.jsonl        - Bridge monitor snapshot (old format)

EXAMPLES:
  # Run with auto-restart (recommended for production):
  python tools/supervisor_start.py

  # Run in monitor-only mode (no auto-fix):
  python tools/supervisor_start.py --no-autofix

  # Slow check interval (less CPU), wider activity window:
  python tools/supervisor_start.py --interval 15 --activity-window-sec 600

  # Run alongside existing bridge_monitor.py:
  python tools/workflow_supervisor.py --interval 10 &
  python tools/bridge_monitor.py --agent --interval 5
        """,
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Check interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--activity-window-sec",
        type=int,
        default=300,
        help="Window to look for recent activity (default: 300)",
    )
    parser.add_argument(
        "--no-update-block-sec",
        type=int,
        default=180,
        help="Seconds before idle message triggers DEGRADED (default: 180)",
    )
    parser.add_argument(
        "--restart-cooldown-sec",
        type=int,
        default=120,
        help="Min seconds between auto-restart attempts (default: 120)",
    )
    parser.add_argument(
        "--stale-cmd-sec",
        type=int,
        default=120,
        help="Seconds before bridge command is stale (default: 120)",
    )
    parser.add_argument(
        "--no-autofix",
        action="store_true",
        help="Disable auto-remediation (monitoring only)",
    )
    args = parser.parse_args()

    workspace_root = Path(__file__).resolve().parents[1]
    supervisor_script = workspace_root / "tools" / "workflow_supervisor.py"

    cmd = [
        str(workspace_root / ".venv" / "Scripts" / "python.exe"),
        str(supervisor_script),
        "--interval",
        str(args.interval),
        "--activity-window-sec",
        str(args.activity_window_sec),
        "--no-update-block-sec",
        str(args.no_update_block_sec),
        "--restart-cooldown-sec",
        str(args.restart_cooldown_sec),
        "--stale-cmd-sec",
        str(args.stale_cmd_sec),
    ]

    if args.no_autofix:
        cmd.append("--no-autofix")

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] Starting Workflow Supervisor")
    print(f"  Workspace: {workspace_root}")
    print(f"  Interval: {args.interval}s")
    print(f"  Auto-fix: {not args.no_autofix}")
    print()

    try:
        result = subprocess.run(cmd, cwd=str(workspace_root))
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
