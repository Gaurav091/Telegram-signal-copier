"""Bridge Monitor — real-time watchdog for MT5 bridge health.

Current bridge contract:
- Python writes *.cmd files to bridge root.
- MT5 EA scans bridge root for *.cmd files.
- MT5 EA writes *.result files to outbox/.

Run:
        .venv\\Scripts\\python.exe tools\\bridge_monitor.py
"""
from __future__ import annotations

import os
import sys
import time
import argparse
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ── Bridge path (same logic as config.py _default_bridge_root) ──────────
BRIDGE_ROOT = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal" / "Common" / "Files" / "TelegramSignalCopierBridge"
INBOX  = BRIDGE_ROOT
OUTBOX = BRIDGE_ROOT / "outbox"
EA_STATUS = BRIDGE_ROOT / "ea_status.txt"
TG_STATUS = BRIDGE_ROOT / "telegram_status.txt"
AUTOFIX_LOG = BRIDGE_ROOT / "autofix_log.txt"

# Thresholds
HEARTBEAT_STALE_SEC = 120   # EA heartbeat older than this = likely not running
CMD_STALE_SEC       = 90    # Cmd file sitting in inbox longer than this = EA not consuming
REFRESH_SEC         = 3
CHECK_MIN_INTERVAL  = 5
HEARTBEAT_FUTURE_SKEW_SEC = 120
MT5_LOG_SCAN_INTERVAL_SEC = 30
INBOX_WARNING_COOLDOWN_SEC = 180
RECOVERING_WINDOW_SEC = 60

_EA_INSTANCE_RE = re.compile(r"TelegramSignalCopierEA\s*\(([^,]+),([^)]+)\)")
_MT5_LOG_ERROR_MARKERS = (
    "inbox scan found no .cmd files",
    "failed",
    "error",
    "invalid",
    "reject",
    "cannot",
    "denied",
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _age(path: Path) -> float:
    """Seconds since file was last modified."""
    try:
        mtime = path.stat().st_mtime
        return time.time() - mtime
    except FileNotFoundError:
        return float("inf")


def _read_ea_status() -> dict[str, str]:
    try:
        text = EA_STATUS.read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    except Exception:
        return {}


def _read_tg_status() -> dict[str, str]:
    try:
        text = TG_STATUS.read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    except Exception:
        return {}


def _append_autofix_log(message: str) -> None:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {message}\n"
    try:
        AUTOFIX_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUTOFIX_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _run_listener_start(workspace_root: Path) -> tuple[bool, str]:
    cmd = [
        str(workspace_root / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "telegram_signal_copier",
        "listen",
    ]
    try:
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

        proc = subprocess.Popen(
            cmd,
            cwd=str(workspace_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        time.sleep(2)
        if proc.poll() is None:
            return True, f"listener started pid={proc.pid}"
        return False, f"listener exited code={proc.returncode}"
    except Exception as exc:
        return False, str(exc)


def _cleanup_stale_smoke_cmds() -> int:
    cleaned = 0
    now = time.time()
    for cmd in BRIDGE_ROOT.glob("smoke-*.cmd"):
        try:
            if now - cmd.stat().st_mtime > 600:
                cmd.unlink(missing_ok=True)
                cleaned += 1
        except Exception:
            continue
    return cleaned


def _mt5_terminal_dirs() -> list[Path]:
    root = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    if not root.exists():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir()]

    def _latest_log_mtime(p: Path) -> float:
        latest = _latest_mql5_log_path(p)
        if not latest:
            return 0.0
        try:
            return latest.stat().st_mtime
        except Exception:
            return 0.0

    return sorted(dirs, key=_latest_log_mtime, reverse=True)


def _latest_mql5_log_path(terminal_dir: Path) -> Path | None:
    log_dir = terminal_dir / "MQL5" / "Logs"
    if not log_dir.exists():
        return None
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _tail_lines(path: Path, max_lines: int = 300) -> list[str]:
    for enc in ("utf-16", "utf-8", "cp1252", "latin-1"):
        try:
            data = path.read_text(encoding=enc, errors="ignore").splitlines()
            if len(data) <= max_lines:
                return data
            return data[-max_lines:]
        except Exception:
            continue
    return []


def _scan_mt5_logs(instance_lines: int = 5000, error_lines: int = 300, max_terminals: int = 20) -> dict[str, object]:
    findings: dict[str, object] = {
        "log_files": [],
        "ea_instances": [],
        "error_hits": [],
        "inbox_path_hits": 0,
    }
    instances: set[tuple[str, str]] = set()
    hits: list[str] = []
    inbox_hits = 0

    terminals = _mt5_terminal_dirs()[:max_terminals]
    for terminal in terminals:
        log_path = _latest_mql5_log_path(terminal)
        if not log_path:
            continue
        findings["log_files"].append(str(log_path))

        # Wide window: discover how many charts/timeframes have this EA attached.
        for line in _tail_lines(log_path, max_lines=instance_lines):
            if "TelegramSignalCopierEA" in line:
                m = _EA_INSTANCE_RE.search(line)
                if m:
                    instances.add((m.group(1).strip(), m.group(2).strip()))

        # Recent window: only recent error signals should affect live health.
        for line in _tail_lines(log_path, max_lines=error_lines):
            if "TelegramSignalCopierEA" not in line:
                continue
            low = line.lower()
            if any(marker in low for marker in _MT5_LOG_ERROR_MARKERS):
                if "inbox/*.cmd" in low:
                    inbox_hits += 1
                if len(hits) < 6:
                    hits.append(line.strip())

    findings["ea_instances"] = [f"{sym},{tf}" for sym, tf in sorted(instances)]
    findings["error_hits"] = hits
    findings["inbox_path_hits"] = inbox_hits
    return findings


def _daily_report_path(workspace_root: Path) -> Path:
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return workspace_root / "logs" / f"bridge_health_{today}.jsonl"


def _append_daily_health_report(
    workspace_root: Path,
    started_at: float,
    verdict: str,
    reasons: list[str],
    reason_counter: Counter[str],
    extra: dict[str, object],
) -> None:
    path = _daily_report_path(workspace_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "uptime_s": round(max(0.0, time.time() - started_at), 1),
            "verdict": verdict,
            "reasons": reasons,
            "reason_totals": dict(reason_counter),
            **extra,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def _color(text: str, code: int) -> str:
    return f"\033[{code}m{text}\033[0m"


def red(t: str)    -> str: return _color(t, 91)
def yellow(t: str) -> str: return _color(t, 93)
def green(t: str)  -> str: return _color(t, 92)
def cyan(t: str)   -> str: return _color(t, 96)
def bold(t: str)   -> str: return _color(t, 1)


def render() -> None:
    os.system("cls" if os.name == "nt" else "clear")
    now_str = _now().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(bold(f"  MT5 Bridge Monitor   {now_str}"))
    print("  " + "─" * 58)

    # ── EA status ──────────────────────────────────────────────────────
    status = _read_ea_status()
    hb_epoch = status.get("heartbeat_epoch", "")
    hb_display = status.get("heartbeat_display", "N/A")
    expert = status.get("expert_name", "?")
    symbol = status.get("chart_symbol", "?")
    last_req = status.get("last_request_id", "(none)")
    last_stat = status.get("last_status", "")
    last_msg  = status.get("last_message", "")

    if hb_epoch:
        hb_age = time.time() - float(hb_epoch)
        if hb_age < HEARTBEAT_STALE_SEC:
            hb_label = green(f"ALIVE  ({hb_age:.0f}s ago)")
        else:
            hb_label = red(f"STALE  ({hb_age:.0f}s ago — EA may not be running)")
    else:
        hb_age = float("inf")
        hb_label = red("NO HEARTBEAT  (ea_status.txt not written by EA)")

    print(f"\n  {bold('EA')}: {expert}  chart={symbol}")
    print(f"  Heartbeat : {hb_label}   ({hb_display})")
    print(f"  Last ID   : {last_req}")
    if last_stat:
        color_fn = green if "EXEC" in last_stat.upper() else yellow
        print(f"  Last status: {color_fn(last_stat)}  {last_msg}")

    # ── Bridge command queue (root) ────────────────────────────────────
    print(f"\n  {bold('COMMAND QUEUE')} ({INBOX})")
    cmds = sorted(INBOX.glob("*.cmd"), key=lambda p: p.stat().st_mtime)
    if not cmds:
        print(green("    ✓  Empty — all commands consumed"))
    else:
        stale_count = 0
        for cmd in cmds[-10:]:   # show last 10
            age = _age(cmd)
            if age > CMD_STALE_SEC:
                stale_count += 1
                label = red(f"STALE {age:.0f}s")
            else:
                label = yellow(f"pending {age:.0f}s")
            # read the command contents briefly
            try:
                lines = {k: v for k, v in (l.split("=", 1) for l in cmd.read_text(encoding="utf-8").splitlines() if "=" in l)}
                summary = f"{lines.get('action','?')} {lines.get('symbol','?')}  sl={lines.get('stop_loss','?')}  tp={lines.get('take_profit','?')}"
            except Exception:
                summary = ""
            print(f"    {label}  {cmd.name[:8]}…  {summary}")

        total = len(cmds)
        # Count only recently-written commands as stale (within last 10 min).
        # Pre-fix backlog files are old but expected — they will be consumed once
        # the EA is reloaded with the TimeGMT() fix.
        recent_stale = [c for c in cmds if CMD_STALE_SEC < _age(c) < 600]
        oldest_age = _age(cmds[0])
        backlog = [c for c in cmds if _age(c) >= 600]

        if recent_stale:
            print(red(f"\n  ⚠  {len(recent_stale)}/{total} recent commands stale! EA is NOT reading bridge queue."))
            print(red(f"     Oldest: {oldest_age:.0f}s  →  Check MT5: Algo Trading ON? EA attached?"))
        elif backlog:
            print(yellow(f"\n  ℹ  {len(backlog)} old backlog commands (>10 min) — will clear once EA is reloaded."))
            print(yellow(f"     {total - len(backlog)} fresh commands OK"))
        else:
            print(yellow(f"\n    {total} pending (recently written, waiting for EA)"))

    # ── Outbox ─────────────────────────────────────────────────────────
    print(f"\n  {bold('OUTBOX')} ({OUTBOX})")
    results = sorted(OUTBOX.glob("*.result"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not results:
        print(red("    ✗  No result files ever written by MT5 EA"))
    else:
        for r in results[:5]:
            try:
                data = {k: v for k, v in (l.split("=", 1) for l in r.read_text(encoding="utf-8").splitlines() if "=" in l)}
                stat = data.get("status", "?")
                ticket = data.get("ticket", "?")
                price  = data.get("executed_price", "?")
                at     = data.get("executed_at", "?")[:19]
                color_fn = green if "EXEC" in stat.upper() or "FILL" in stat.upper() else red
                print(f"    {color_fn(stat)}  ticket={ticket}  price={price}  {at}  {r.name[:8]}…")
            except Exception as exc:
                print(f"    {r.name}: {exc}")

    # ── Summary verdict ────────────────────────────────────────────────
    print("\n  " + "─" * 58)
    inbox_stale = any(_age(c) > CMD_STALE_SEC for c in cmds)
    ea_alive = hb_age < HEARTBEAT_STALE_SEC
    has_results = bool(results)

    if ea_alive and not inbox_stale and has_results:
        print(green("  ✓  WORKING: EA alive, consuming commands, writing results"))
    elif ea_alive and inbox_stale:
        print(red("  ✗  BLOCKED: EA heartbeat OK but bridge commands are stale"))
        print(red("       → In MT5: verify Algo Trading button is GREEN"))
        print(red("       → Verify EA 'TelegramSignalCopierEA' attached to chart"))
        print(red("       → Check Expert tab in MT5 for error messages"))
    elif not ea_alive:
        print(red("  ✗  OFFLINE: EA heartbeat stale or missing"))
        print(red("       → Open MT5, attach EA to XAUUSDm chart"))
    elif not has_results:
        print(yellow("  ⚠  No results yet — waiting for first EA execution"))

    print(f"\n  Refreshing every {REFRESH_SEC}s — Ctrl+C to quit\n")


def run_agent_mode(
    workspace_root: Path,
    interval: int,
    autofix: bool,
    inbox_warning_cooldown_sec: int,
    recovering_window_sec: int,
) -> None:
    print(f"Autonomous monitor mode ON  interval={interval}s  autofix={autofix}")
    print(f"Bridge root: {BRIDGE_ROOT}")
    print("Ctrl+C to stop")

    started_at = time.time()
    reason_counter: Counter[str] = Counter()
    last_report_ts = 0.0
    last_log_scan_ts = 0.0
    mt5_scan: dict[str, object] = {
        "log_files": [],
        "ea_instances": [],
        "error_hits": [],
        "inbox_path_hits": 0,
    }
    last_non_healthy_ts = started_at
    last_inbox_warning_ts: float | None = None
    last_inbox_warning_signature = ""

    while True:
        ea = _read_ea_status()
        tg = _read_tg_status()

        hb_epoch = ea.get("heartbeat_epoch")
        ea_age = (time.time() - float(hb_epoch)) if hb_epoch else float("inf")
        ea_clock_skew = ea_age < -HEARTBEAT_FUTURE_SKEW_SEC
        ea_alive = (ea_age < HEARTBEAT_STALE_SEC) and (not ea_clock_skew)

        tg_hb = tg.get("heartbeat_epoch")
        tg_age = (time.time() - float(tg_hb)) if tg_hb else float("inf")
        listener_alive = tg_age < HEARTBEAT_STALE_SEC

        cmd_files = sorted(BRIDGE_ROOT.glob("*.cmd"), key=lambda p: p.stat().st_mtime)
        result_files = sorted(OUTBOX.glob("*.result"), key=lambda p: p.stat().st_mtime, reverse=True)
        stale_cmds = [c for c in cmd_files if _age(c) > CMD_STALE_SEC and _age(c) < 600]

        now = time.time()
        if now - last_log_scan_ts >= MT5_LOG_SCAN_INTERVAL_SEC:
            mt5_scan = _scan_mt5_logs(instance_lines=5000, error_lines=300, max_terminals=20)
            last_log_scan_ts = now

        ea_instances = mt5_scan.get("ea_instances", [])
        mt5_error_hits = mt5_scan.get("error_hits", [])
        inbox_path_hits = int(mt5_scan.get("inbox_path_hits", 0) or 0)

        inbox_error_lines = [line for line in mt5_error_hits if "inbox/*.cmd" in line.lower()]
        inbox_signature = "||".join(inbox_error_lines)
        if inbox_error_lines and inbox_signature != last_inbox_warning_signature:
            last_inbox_warning_ts = now
            last_inbox_warning_signature = inbox_signature

        inbox_warning_active = False
        inbox_warning_age: float | None = None
        if last_inbox_warning_ts is not None:
            inbox_warning_age = now - last_inbox_warning_ts
            if inbox_warning_age < inbox_warning_cooldown_sec:
                inbox_warning_active = True

        verdict = "HEALTHY"
        reasons: list[str] = []

        if not listener_alive:
            verdict = "DEGRADED"
            reasons.append("telegram listener heartbeat stale")
        if not ea_alive:
            verdict = "DEGRADED"
            reasons.append("mt5 ea heartbeat stale")
        if ea_clock_skew:
            verdict = "BLOCKED"
            reasons.append("mt5 ea heartbeat in future (likely old TimeLocal build attached)")
        if stale_cmds:
            verdict = "BLOCKED"
            reasons.append(f"{len(stale_cmds)} stale cmd file(s)")
        if inbox_warning_active:
            verdict = "BLOCKED"
            remaining = int(max(0, inbox_warning_cooldown_sec - (inbox_warning_age or 0)))
            reasons.append(f"mt5 inbox-path warning cooling down ({remaining}s left)")
        if len(ea_instances) > 1:
            if verdict == "HEALTHY":
                verdict = "DEGRADED"
            reasons.append(f"multiple EA instances detected ({len(ea_instances)})")
        if mt5_error_hits and verdict == "HEALTHY":
            verdict = "DEGRADED"
            reasons.append("recent mt5 copier log errors detected")

        if verdict != "HEALTHY":
            last_non_healthy_ts = now
        else:
            stable_for = now - last_non_healthy_ts
            if stable_for < recovering_window_sec:
                verdict = "RECOVERING"
                reasons.append(f"stability window {int(stable_for)}s/{recovering_window_sec}s")

        for reason in reasons:
            reason_counter[reason] += 1

        # Safety: autonomous mode never injects trade commands.
        # Health is assessed passively from heartbeat + queue movement + outbox activity.

        # Auto-remediation: safe + local only.
        if autofix:
            cleaned = _cleanup_stale_smoke_cmds()
            if cleaned:
                _append_autofix_log(f"removed {cleaned} stale smoke cmd file(s)")

            if not listener_alive:
                ok, detail = _run_listener_start(workspace_root)
                if ok:
                    _append_autofix_log("listener restart attempted: success")
                else:
                    _append_autofix_log(f"listener restart attempted: failed ({detail})")

        if now - last_report_ts >= 60:
            _append_daily_health_report(
                workspace_root=workspace_root,
                started_at=started_at,
                verdict=verdict,
                reasons=reasons,
                reason_counter=reason_counter,
                extra={
                    "ea_alive": ea_alive,
                    "listener_alive": listener_alive,
                    "pending_cmd": len(cmd_files),
                    "stale_cmd_recent": len(stale_cmds),
                    "ea_instances": ea_instances,
                    "mt5_log_files": mt5_scan.get("log_files", []),
                },
            )
            last_report_ts = now

        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(
            json.dumps(
                {
                    "ts": ts,
                    "verdict": verdict,
                    "reasons": reasons,
                    "ea_alive": ea_alive,
                    "ea_age_s": round(ea_age, 1) if ea_age != float("inf") else None,
                    "ea_clock_skew": ea_clock_skew,
                    "listener_alive": listener_alive,
                    "listener_age_s": round(tg_age, 1) if tg_age != float("inf") else None,
                    "pending_cmd": len(cmd_files),
                    "stale_cmd_recent": len(stale_cmds),
                    "recent_results": len(result_files[:5]),
                    "ea_instances": ea_instances,
                    "mt5_error_count": len(mt5_error_hits),
                    "mt5_error_sample": mt5_error_hits[:2],
                    "inbox_path_hits_recent_scan": inbox_path_hits,
                    "inbox_warning_active": inbox_warning_active,
                    "inbox_warning_age_s": round(inbox_warning_age, 1) if inbox_warning_age is not None else None,
                    "recovering_window_sec": recovering_window_sec,
                    "smoke_pending": "",
                }
            ),
            flush=True,
        )
        time.sleep(max(CHECK_MIN_INTERVAL, interval))


def main() -> None:
    parser = argparse.ArgumentParser(description="MT5 bridge monitor")
    parser.add_argument("--agent", action="store_true", help="run in autonomous supervisor mode")
    parser.add_argument("--interval", type=int, default=REFRESH_SEC, help="check interval seconds")
    parser.add_argument("--no-autofix", action="store_true", help="disable auto remediation actions")
    parser.add_argument("--inbox-warning-cooldown-sec", type=int, default=INBOX_WARNING_COOLDOWN_SEC, help="seconds to keep inbox-path warning active without new hits")
    parser.add_argument("--recovering-window-sec", type=int, default=RECOVERING_WINDOW_SEC, help="seconds to remain in RECOVERING before HEALTHY")
    args = parser.parse_args()

    if not BRIDGE_ROOT.exists():
        print(red(f"Bridge folder not found: {BRIDGE_ROOT}"))
        sys.exit(1)

    workspace_root = Path(__file__).resolve().parents[1]

    if args.agent:
        run_agent_mode(
            workspace_root=workspace_root,
            interval=max(CHECK_MIN_INTERVAL, int(args.interval)),
            autofix=not args.no_autofix,
            inbox_warning_cooldown_sec=max(30, int(args.inbox_warning_cooldown_sec)),
            recovering_window_sec=max(10, int(args.recovering_window_sec)),
        )
        return

    print(f"Monitoring bridge at:\n  {BRIDGE_ROOT}\n")
    print("Press Ctrl+C to stop.\n")
    time.sleep(1)

    try:
        while True:
            render()
            time.sleep(REFRESH_SEC)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
