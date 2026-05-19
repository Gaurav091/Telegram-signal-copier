"""Smart Supervisor — self-optimizing monitoring loop.

Combines real-time pipeline health monitoring with autonomous code fixing.

Architecture
------------

  ┌─────────────────────────────────────────────────────────────────┐
  │                      SMART SUPERVISOR                           │
  │                                                                 │
  │  Every --interval seconds:                                      │
  │  1. READ   pipeline_*.jsonl  (last N entries)                   │
  │  2. CHECK  bridge health  (ea_status.txt, bridge inbox)         │
  │  3. DETECT failure pattern  (classify_failures)                 │
  │  4. FIX    → developer_agent generates & applies patch          │
  │  5. VERIFY → restart listener, watch next N signals             │
  │  6. ROLLBACK if failure recurs within grace period              │
  │                                                                 │
  │  Verdicts: HEALTHY / DEGRADED / BLOCKED / FIXING / RECOVERING  │
  └─────────────────────────────────────────────────────────────────┘

Usage
-----
  # Full autonomy (monitor + fix + restart):
  python tools/smart_supervisor.py

  # Monitor only (no code changes):
  python tools/smart_supervisor.py --no-fix

  # Aggressive mode (shorter windows):
  python tools/smart_supervisor.py --interval 10 --sample-window 30

  # Log to file:
  python tools/smart_supervisor.py 2>&1 | tee logs/smart_supervisor.log
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

# ── Setup path so we can import src/ ────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("smart_supervisor")

UTC = timezone.utc

# ── Bridge paths ─────────────────────────────────────────────────────────────
BRIDGE_ROOT = (
    Path(os.environ.get("APPDATA", ""))
    / "MetaQuotes" / "Terminal" / "Common" / "Files" / "TelegramSignalCopierBridge"
)
EA_STATUS    = BRIDGE_ROOT / "ea_status.txt"
TG_STATUS    = BRIDGE_ROOT / "telegram_status.txt"
BRIDGE_INBOX = BRIDGE_ROOT
BRIDGE_OUTBOX = BRIDGE_ROOT / "outbox"
LOGS_DIR     = ROOT / "logs"

# ── Thresholds ────────────────────────────────────────────────────────────────
HEARTBEAT_STALE_SEC   = 120
CMD_STALE_SEC         = 90
GRACE_PERIOD_SEC      = 300   # after a fix, wait this long before re-evaluating
MAX_FIX_ATTEMPTS      = 3     # per category per session
FIX_COOLDOWN_SEC      = 180   # min seconds between fix attempts


# ══════════════════════════════════════════════════════════════════════════════
# State tracking
# ══════════════════════════════════════════════════════════════════════════════

class SupervisorState:
    def __init__(self) -> None:
        self.started_at      = time.time()
        self.last_fix_ts: dict[str, float] = {}   # category → last fix timestamp
        self.fix_attempts:  dict[str, int]  = {}   # category → count
        self.last_verdict    = "UNKNOWN"
        self.post_fix_watch: dict[str, float] = {} # category → grace window end ts
        self.last_report_ts  = 0.0
        self.log_path_cache: Path | None = None


# ══════════════════════════════════════════════════════════════════════════════
# Log reading
# ══════════════════════════════════════════════════════════════════════════════

def _current_pipeline_log() -> Path | None:
    today = datetime.now(tz=UTC).strftime("%Y%m%d")
    yesterday = datetime.fromtimestamp(time.time() - 86400, tz=UTC).strftime("%Y%m%d")
    for date in (today, yesterday):
        p = LOGS_DIR / f"pipeline_{date}.jsonl"
        if p.exists():
            return p
    # fallback: most recent
    logs = sorted(LOGS_DIR.glob("pipeline_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _read_recent_pipeline_logs(n: int = 100) -> list[dict]:
    path = _current_pipeline_log()
    if not path:
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(entries) >= n:
                break
        return list(reversed(entries))
    except Exception as exc:
        logger.warning("Failed to read pipeline log: %s", exc)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# Bridge / EA health
# ══════════════════════════════════════════════════════════════════════════════

def _read_kv(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    except Exception:
        return {}


def _heartbeat_age(kv: dict[str, str]) -> float:
    ts = kv.get("heartbeat_epoch")
    if not ts:
        return float("inf")
    try:
        return time.time() - float(ts)
    except Exception:
        return float("inf")


def _bridge_health() -> dict:
    ea  = _read_kv(EA_STATUS)
    tg  = _read_kv(TG_STATUS)
    cmds  = list(BRIDGE_INBOX.glob("*.cmd")) if BRIDGE_INBOX.exists() else []
    now   = time.time()
    stale = [f for f in cmds if now - f.stat().st_mtime > CMD_STALE_SEC]
    return {
        "ea_heartbeat_age":  _heartbeat_age(ea),
        "tg_heartbeat_age":  _heartbeat_age(tg),
        "listener_state":    tg.get("listener_state", "unknown"),
        "last_decision":     tg.get("last_decision", ""),
        "last_exec_status":  tg.get("last_execution_status", ""),
        "pending_cmds":      len(cmds),
        "stale_cmds":        len(stale),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Verdict computation
# ══════════════════════════════════════════════════════════════════════════════

def _compute_verdict(bridge: dict, failure) -> tuple[str, list[str]]:
    reasons: list[str] = []

    # Critical infrastructure checks
    if bridge["ea_heartbeat_age"] > HEARTBEAT_STALE_SEC:
        reasons.append(f"MT5 EA offline (heartbeat {bridge['ea_heartbeat_age']:.0f}s old)")
    if bridge["tg_heartbeat_age"] > HEARTBEAT_STALE_SEC:
        reasons.append(f"Telegram listener offline (heartbeat {bridge['tg_heartbeat_age']:.0f}s old)")
    if bridge["listener_state"] in ("error", "stopped"):
        reasons.append(f"Listener state={bridge['listener_state']}")
    if bridge["stale_cmds"] > 0:
        reasons.append(f"{bridge['stale_cmds']} stale bridge command(s)")

    if reasons:
        return "BLOCKED", reasons

    # Soft failures from pipeline logs
    if failure is not None:
        reasons.append(failure.description)
        return "DEGRADED", reasons

    return "HEALTHY", []


# ══════════════════════════════════════════════════════════════════════════════
# Listener restart
# ══════════════════════════════════════════════════════════════════════════════

def _restart_listener() -> bool:
    script = ROOT / "tools" / "restart_listener.py"
    if not script.exists():
        logger.error("restart_listener.py not found")
        return False
    try:
        r = subprocess.run(
            [str(ROOT / ".venv" / "Scripts" / "python.exe"), str(script)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=90,
        )
        if r.returncode == 0:
            logger.info("Listener restarted OK")
            return True
        logger.warning("Listener restart failed: %s", r.stderr[:300])
        return False
    except Exception as exc:
        logger.error("Listener restart error: %s", exc)
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Developer agent invocation
# ══════════════════════════════════════════════════════════════════════════════

def _try_fix(failure, state: SupervisorState, args) -> bool:
    """Attempt to apply a developer-agent fix for the failure. Returns True if applied."""
    from telegram_signal_copier.agents.developer_agent import generate_patch, apply_patch
    from telegram_signal_copier.config import AppConfig
    from telegram_signal_copier.services.openai_client import OpenAIClient

    category = failure.category

    # Rate limiting
    now = time.time()
    if now - state.last_fix_ts.get(category, 0) < FIX_COOLDOWN_SEC:
        logger.info("[FIX] Cooldown active for %s — skipping", category)
        return False
    if state.fix_attempts.get(category, 0) >= MAX_FIX_ATTEMPTS:
        logger.warning("[FIX] Max fix attempts (%d) reached for %s", MAX_FIX_ATTEMPTS, category)
        return False

    logger.info("[FIX] Generating patch for %s: %s", category, failure.description)

    try:
        cfg = AppConfig.from_env(ROOT)
        client = OpenAIClient(cfg)
    except Exception as exc:
        logger.error("[FIX] Cannot create LLM client: %s", exc)
        return False

    try:
        patch = generate_patch(failure, ROOT, client)
    except Exception as exc:
        logger.error("[FIX] generate_patch raised: %s", exc)
        patch = None

    if patch is None:
        logger.warning("[FIX] No patch generated for %s", category)
        state.fix_attempts[category] = state.fix_attempts.get(category, 0) + 1
        return False

    logger.info("[FIX] Applying patch: %s → %s", patch.file_path, patch.explanation)

    try:
        ok = apply_patch(patch, ROOT)
    except Exception as exc:
        logger.error("[FIX] apply_patch raised: %s", exc)
        ok = False

    state.fix_attempts[category] = state.fix_attempts.get(category, 0) + 1
    state.last_fix_ts[category] = now

    if ok:
        state.post_fix_watch[category] = now + GRACE_PERIOD_SEC
        logger.info("[FIX] ✓ Patch applied for %s — restarting listener for changes to take effect", category)
        _restart_listener()
        return True

    logger.warning("[FIX] ✗ Patch application failed for %s", category)
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Post-fix verification
# ══════════════════════════════════════════════════════════════════════════════

def _check_post_fix(failure, state: SupervisorState) -> None:
    """If we're in a grace window and the same failure is still occurring, rollback."""
    if failure is None:
        return

    category = failure.category
    grace_end = state.post_fix_watch.get(category)
    if grace_end is None:
        return

    now = time.time()
    if now < grace_end:
        logger.info("[VERIFY] In grace window for %s (%.0fs remaining) — monitoring", category, grace_end - now)
        return

    # Grace window expired — failure still present
    logger.warning("[VERIFY] Fix for %s did NOT resolve the issue — rolling back", category)
    _do_rollback(category)
    del state.post_fix_watch[category]


def _do_rollback(category: str) -> None:
    from telegram_signal_copier.agents.developer_agent import (
        _CATEGORY_FILES, rollback_last_patch
    )
    files = _CATEGORY_FILES.get(category, [])
    for fp in files:
        logger.info("[ROLLBACK] Rolling back %s", fp)
        rollback_last_patch(ROOT, fp)
    _restart_listener()


# ══════════════════════════════════════════════════════════════════════════════
# Report output
# ══════════════════════════════════════════════════════════════════════════════

def _emit_report(verdict: str, reasons: list[str], bridge: dict, failure, actions: list[str]) -> None:
    report = {
        "ts":       datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "verdict":  verdict,
        "reasons":  reasons,
        "actions":  actions,
        "bridge": {
            "ea_hb_age_s":    round(bridge["ea_heartbeat_age"], 1) if bridge["ea_heartbeat_age"] != float("inf") else None,
            "tg_hb_age_s":    round(bridge["tg_heartbeat_age"], 1) if bridge["tg_heartbeat_age"] != float("inf") else None,
            "listener_state": bridge["listener_state"],
            "last_decision":  bridge["last_decision"],
            "last_exec":      bridge["last_exec_status"],
            "pending_cmds":   bridge["pending_cmds"],
            "stale_cmds":     bridge["stale_cmds"],
        },
        "failure": {
            "category": failure.category,
            "count":    failure.count,
            "total":    failure.total_signals,
        } if failure else None,
    }
    line = json.dumps(report)
    print(line, flush=True)

    # Also append to daily JSONL
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    log_path = LOGS_DIR / f"smart_supervisor_{today}.jsonl"
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Main loop
# ══════════════════════════════════════════════════════════════════════════════

def run(args) -> None:
    from telegram_signal_copier.agents.developer_agent import classify_failures

    state = SupervisorState()
    logger.info("Smart Supervisor started. interval=%ds fix=%s", args.interval, not args.no_fix)
    logger.info("Pipeline logs: %s", LOGS_DIR)
    logger.info("Bridge root:   %s", BRIDGE_ROOT)

    report_interval = args.report_interval

    while True:
        loop_start = time.time()
        actions: list[str] = []

        # 1. Read pipeline logs
        recent_logs = _read_recent_pipeline_logs(n=args.sample_window)

        # 2. Bridge health
        bridge = _bridge_health()

        # 3. Classify failures
        failure = classify_failures(recent_logs, window=args.sample_window)

        # 4. Check post-fix grace windows
        _check_post_fix(failure, state)

        # 5. Auto-restart listener if BLOCKED due to listener being offline
        if (
            bridge["tg_heartbeat_age"] > HEARTBEAT_STALE_SEC
            or bridge["listener_state"] in ("error", "stopped")
        ) and not args.no_fix:
            logger.warning("Listener offline — attempting restart")
            ok = _restart_listener()
            actions.append(f"restart_listener={'ok' if ok else 'failed'}")

        # 6. Apply developer fix if failure detected and not in grace window
        if (
            failure is not None
            and not args.no_fix
            and failure.category not in state.post_fix_watch
            and failure.count >= args.min_failures
        ):
            fixed = _try_fix(failure, state, args)
            if fixed:
                actions.append(f"dev_agent_fix={failure.category}")

        # 7. Compute verdict
        verdict, reasons = _compute_verdict(bridge, failure)

        # 8. Emit report at report_interval
        now = time.time()
        if now - state.last_report_ts >= report_interval or verdict != state.last_verdict:
            _emit_report(verdict, reasons, bridge, failure, actions)
            state.last_report_ts = now
            if verdict != state.last_verdict:
                state.last_verdict = verdict

        # Sleep remainder of interval
        elapsed = time.time() - loop_start
        sleep_time = max(0.5, args.interval - elapsed)
        time.sleep(sleep_time)


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smart Supervisor — pipeline monitoring + autonomous code fixing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES
  # Full autonomy (recommended for production):
  python tools/smart_supervisor.py

  # Monitor only, no code changes:
  python tools/smart_supervisor.py --no-fix

  # Fast iteration, aggressive fixing:
  python tools/smart_supervisor.py --interval 10 --sample-window 30 --min-failures 2

  # High-frequency trading (tight thresholds):
  python tools/smart_supervisor.py --interval 5 --sample-window 20 --min-failures 2

VERDICTS
  HEALTHY    All components alive, no recurring failure pattern
  DEGRADED   Failure pattern detected (fixing in progress or paused)
  BLOCKED    Critical: listener offline, EA offline, stale bridge commands
  FIXING     Developer agent is generating and applying a patch

OUTPUT
  JSON lines to stdout + logs/smart_supervisor_YYYY-MM-DD.jsonl
""",
    )
    parser.add_argument("--interval",       type=int,   default=30,  help="Check interval in seconds (default: 30)")
    parser.add_argument("--sample-window",  type=int,   default=50,  help="Number of recent log entries to analyse (default: 50)")
    parser.add_argument("--min-failures",   type=int,   default=3,   help="Minimum failure count to trigger a fix (default: 3)")
    parser.add_argument("--report-interval",type=int,   default=60,  help="Seconds between report lines when verdict unchanged (default: 60)")
    parser.add_argument("--no-fix",         action="store_true",     help="Disable code fixing (monitor only)")
    args = parser.parse_args()

    try:
        run(args)
    except KeyboardInterrupt:
        logger.info("Smart Supervisor stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
