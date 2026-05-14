#!/usr/bin/env python3
"""
Log Monitor Agent — tails project logs and detects/fixes recurring issues.

Detected patterns
-----------------
FLOOD_WAIT       Telegram FloodWait during source resolution → skips restart until wait expires
CRASH_LOOP       Listener restarting > N times in M minutes → throttles restart cooldown
RATE_LIMIT       All AI providers tripped/rate-limited → logs provider status
STALE_CMDS       Stale bridge .cmd files older than threshold → optionally purges
LISTENER_DOWN    Listener heartbeat stale → triggers restart via restart_listener.py

Usage
-----
  python tools/log_monitor_agent.py --daemon --interval 30
  python tools/log_monitor_agent.py --once
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from collections import deque
from datetime import datetime, timezone

WORKSPACE = Path(__file__).resolve().parents[1]
LOG_DIR = WORKSPACE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
AGENT_LOG = LOG_DIR / "log_monitor_agent.log"

logging.basicConfig(
    filename=AGENT_LOG,
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
)
_root = logging.getLogger()
if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
           for h in _root.handlers):
    _console = logging.StreamHandler()
    _console.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    _root.addHandler(_console)
log = logging.getLogger(__name__)

BRIDGE_ROOT = (
    Path(os.environ.get("APPDATA", ""))
    / "MetaQuotes" / "Terminal" / "Common" / "Files" / "TelegramSignalCopierBridge"
)

# ──────────────────────────────────────────────────────────────────────────────
# Pattern definitions
# ──────────────────────────────────────────────────────────────────────────────

_FLOOD_WAIT_RE = re.compile(
    r"A wait of (\d+) seconds is required \(caused by SearchRequest\)", re.IGNORECASE
)
_LISTENER_CRASHED_RE = re.compile(r"Listener crashed:", re.IGNORECASE)
_RATE_LIMIT_RE = re.compile(r"All AI providers failed|Rate limit exceeded|tripped until", re.IGNORECASE)
_RESTART_ATTEMPT_RE = re.compile(r"Restarting listener in \d+s \(attempt (\d+)\)", re.IGNORECASE)


def _tail(path: Path, max_bytes: int = 500_000) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
        return data.decode("utf-8", errors="ignore").splitlines()
    except Exception:
        return []


def _recent_lines(lines: list[str], window_seconds: int = 300) -> list[str]:
    """Return only lines whose timestamp falls within the last window_seconds."""
    cutoff = time.time() - window_seconds
    result = []
    for line in lines:
        if len(line) < 23:
            continue
        try:
            ts = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f").replace(
                tzinfo=timezone.utc
            ).timestamp()
            if ts >= cutoff:
                result.append(line)
        except Exception:
            pass
    return result


def _restart_listener() -> bool:
    script = WORKSPACE / "tools" / "restart_listener.py"
    try:
        # Use DEVNULL to avoid inheriting any pipes into restart_listener.py.
        # The script prints to its own stdout; we don't need to capture it —
        # it logs to listener-restart.log itself.
        r = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(WORKSPACE),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        log.info("restart_listener.py exited with code %d", r.returncode)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        log.info("restart_listener timed out — child already spawned (OK)")
        return True
    except Exception as exc:
        log.warning("restart_listener failed: %s", exc)
        return False


def _clear_stale_cmds(max_age_seconds: int = 300) -> int:
    cleared = 0
    now = time.time()
    for f in BRIDGE_ROOT.glob("*.cmd"):
        try:
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink()
                log.info("Cleared stale bridge command: %s", f.name)
                cleared += 1
        except Exception:
            pass
    return cleared


# ──────────────────────────────────────────────────────────────────────────────
# Monitor state
# ──────────────────────────────────────────────────────────────────────────────

class LogMonitorAgent:
    def __init__(
        self,
        interval_sec: int = 30,
        crash_loop_threshold: int = 4,
        crash_loop_window: int = 300,
        stale_cmd_sec: int = 300,
        auto_fix: bool = True,
    ) -> None:
        self.interval_sec = interval_sec
        self.crash_loop_threshold = crash_loop_threshold
        self.crash_loop_window = crash_loop_window
        self.stale_cmd_sec = stale_cmd_sec
        self.auto_fix = auto_fix

        self._flood_wait_until: float = 0.0       # epoch: don't restart until this
        self._last_restart_ts: float = 0.0
        self._restart_cooldown: int = 120
        self._recent_crashes: deque[float] = deque(maxlen=20)
        self._ai_rate_limit_notified_at: float = 0.0

    def _log_sources(self) -> list[Path]:
        """All log files to monitor."""
        return [
            LOG_DIR / "telegram_signal_copier.log",
            LOG_DIR / "listener-restart.log",
        ]

    def run_once(self) -> dict:
        report: dict = {
            "ts": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "flood_wait": None,
            "crash_loop": False,
            "ai_rate_limited": False,
            "stale_cmds_cleared": 0,
            "actions": [],
        }
        now = time.time()

        # Collect recent log lines
        recent: list[str] = []
        for path in self._log_sources():
            lines = _tail(path)
            recent.extend(_recent_lines(lines, window_seconds=max(self.crash_loop_window, 600)))

        # ── Detect FloodWait ────────────────────────────────────────────────
        for line in reversed(recent):
            m = _FLOOD_WAIT_RE.search(line)
            if m:
                wait_sec = int(m.group(1))
                flood_expire = now + wait_sec
                if flood_expire > self._flood_wait_until:
                    self._flood_wait_until = flood_expire
                    expire_str = datetime.fromtimestamp(flood_expire, tz=timezone.utc).strftime("%H:%M:%S UTC")
                    msg = f"FLOOD_WAIT: {wait_sec}s detected — suppressing listener restarts until {expire_str}"
                    log.warning(msg)
                    report["flood_wait"] = wait_sec
                    report["actions"].append(msg)
                break

        # ── Detect crash loop ───────────────────────────────────────────────
        crash_times: list[float] = []
        for line in recent:
            if _LISTENER_CRASHED_RE.search(line):
                try:
                    ts = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f").replace(
                        tzinfo=timezone.utc
                    ).timestamp()
                    if now - ts <= self.crash_loop_window:
                        crash_times.append(ts)
                except Exception:
                    pass

        if len(crash_times) >= self.crash_loop_threshold:
            report["crash_loop"] = True
            msg = f"CRASH_LOOP: {len(crash_times)} crashes in {self.crash_loop_window}s window"
            log.warning(msg)
            report["actions"].append(msg)
            # Escalate cooldown to avoid hammering Telegram
            self._restart_cooldown = min(600, self._restart_cooldown * 2)
            log.info("Escalated restart cooldown to %ds", self._restart_cooldown)
        else:
            # De-escalate when calm
            self._restart_cooldown = max(120, self._restart_cooldown // 2)

        # ── Detect AI rate limits ───────────────────────────────────────────
        ai_hits = [l for l in recent[-100:] if _RATE_LIMIT_RE.search(l)]
        if ai_hits and (now - self._ai_rate_limit_notified_at) > 300:
            report["ai_rate_limited"] = True
            msg = f"AI_RATE_LIMIT: {len(ai_hits)} hits in recent window — providers throttled"
            log.info(msg)
            report["actions"].append(msg)
            self._ai_rate_limit_notified_at = now

        # ── Clear stale bridge commands ─────────────────────────────────────
        if self.auto_fix:
            cleared = _clear_stale_cmds(self.stale_cmd_sec)
            if cleared:
                msg = f"STALE_CMDS: cleared {cleared} stale bridge command(s)"
                log.info(msg)
                report["stale_cmds_cleared"] = cleared
                report["actions"].append(msg)

        # ── Check listener heartbeat ────────────────────────────────────────
        tg_status_path = BRIDGE_ROOT / "telegram_status.txt"
        listener_stale = False
        try:
            kv = dict(
                line.split("=", 1)
                for line in tg_status_path.read_text(encoding="utf-8").splitlines()
                if "=" in line
            )
            heartbeat_epoch = float(kv.get("heartbeat_epoch", 0))
            age = now - heartbeat_epoch
            # Give a fresh listener 3 minutes to connect and write its first heartbeat
            # before flagging as stale
            grace = 180
            recent_restart = (now - self._last_restart_ts) < grace
            if age > 180 and not recent_restart:
                listener_stale = True
                log.warning("LISTENER_STALE: heartbeat age=%.0fs", age)
            elif age > 180 and recent_restart:
                log.info("LISTENER_STALE: heartbeat age=%.0fs but within restart grace window", age)
        except Exception:
            pass

        # ── Auto-restart listener if needed ────────────────────────────────
        if self.auto_fix and listener_stale:
            flood_blocked = now < self._flood_wait_until
            cooldown_ok = (now - self._last_restart_ts) >= self._restart_cooldown
            if flood_blocked:
                wait_left = int(self._flood_wait_until - now)
                msg = f"LISTENER_DOWN but FLOOD_WAIT active ({wait_left}s left) — skipping restart"
                log.warning(msg)
                report["actions"].append(msg)
            elif not cooldown_ok:
                msg = f"LISTENER_DOWN but cooldown active ({int(self._restart_cooldown - (now - self._last_restart_ts))}s left)"
                log.info(msg)
                report["actions"].append(msg)
            else:
                msg = "LISTENER_DOWN: triggering restart via restart_listener.py"
                log.info(msg)
                ok = _restart_listener()
                self._last_restart_ts = now
                status = "OK" if ok else "FAILED"
                full_msg = f"{msg} → {status}"
                report["actions"].append(full_msg)

        print(f"[LOG_MONITOR] {report['ts']} actions={report['actions'] or 'none'}", flush=True)
        return report

    def run_daemon(self) -> None:
        log.info(
            "LogMonitorAgent daemon started: interval=%ds auto_fix=%s",
            self.interval_sec, self.auto_fix,
        )
        try:
            print(f"Log monitor daemon ON interval={self.interval_sec}s auto_fix={self.auto_fix}", flush=True)
            print(f"Watching: {[str(p) for p in self._log_sources()]}", flush=True)
        except OSError:
            pass
        try:
            while True:
                try:
                    self.run_once()
                except Exception as exc:
                    log.exception("run_once error: %s", exc)
                time.sleep(self.interval_sec)
        except KeyboardInterrupt:
            log.info("LogMonitorAgent stopped by KeyboardInterrupt")
            try:
                print("Log monitor stopped.", flush=True)
            except OSError:
                pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Log monitor agent")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--no-autofix", dest="auto_fix", action="store_false")
    ap.add_argument("--stale-cmd-sec", type=int, default=300)
    ap.add_argument("--crash-loop-threshold", type=int, default=4)
    args = ap.parse_args()

    agent = LogMonitorAgent(
        interval_sec=args.interval,
        auto_fix=args.auto_fix,
        stale_cmd_sec=args.stale_cmd_sec,
        crash_loop_threshold=args.crash_loop_threshold,
    )

    if args.once:
        agent.run_once()
    elif args.daemon:
        agent.run_daemon()
    else:
        ap.print_help()


if __name__ == "__main__":
    try:
        main()
    except Exception as _exc:
        logging.getLogger(__name__).exception("Unhandled exception in log_monitor_agent: %s", _exc)
        sys.exit(1)
