"""Smart Supervisor — self-optimizing monitoring loop.

Combines real-time pipeline health monitoring with autonomous code fixing
AND missed-trade analysis from raw Telegram message logs.

Architecture
------------

  ┌─────────────────────────────────────────────────────────────────────┐
  │                       SMART SUPERVISOR                              │
  │                                                                     │
  │  Every --interval seconds:                                          │
  │  1. READ   pipeline_*.jsonl          (last N processed signals)     │
  │  2. READ   telegram_messages_*.jsonl (last 200 raw messages)        │
  │  3. CHECK  bridge health             (ea_status.txt, inbox)         │
  │  4. CROSS-REFERENCE: find messages received but not in pipeline     │
  │  5. DRY-RUN missed / rejected messages through pipeline             │
  │  6. DETECT failure pattern  → classify root cause                   │
  │  7. FIX    → developer_agent generates & applies patch              │
  │  8. VERIFY → restart listener, watch next N signals                 │
  │  9. ROLLBACK if failure recurs within grace window                  │
  │                                                                     │
  │  Verdicts: HEALTHY / DEGRADED / BLOCKED / FIXING / RECOVERING      │
  └─────────────────────────────────────────────────────────────────────┘

Usage
-----
  python tools/smart_supervisor.py                  # full autonomy
  python tools/smart_supervisor.py --no-fix         # monitor only
  python tools/smart_supervisor.py --interval 10    # faster checks
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
from collections import Counter
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


def _read_raw_messages(n: int = 200) -> list[dict]:
    """Read last *n* entries from telegram_messages_*.jsonl raw message logs."""
    today = datetime.now(tz=UTC).strftime("%Y%m%d")
    yesterday = datetime.fromtimestamp(time.time() - 86400, tz=UTC).strftime("%Y%m%d")
    entries: list[dict] = []
    for date in (today, yesterday):
        p = LOGS_DIR / f"telegram_messages_{date}.jsonl"
        if not p.exists():
            continue
        try:
            for line in reversed(p.read_text(encoding="utf-8").splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(entries) >= n:
                    break
        except Exception as exc:
            logger.warning("Failed to read raw message log %s: %s", p, exc)
        if len(entries) >= n:
            break
    return list(reversed(entries[-n:]))


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
# Missed-trade analysis
# ══════════════════════════════════════════════════════════════════════════════

# Simple keyword heuristic — messages matching these are candidate trade signals
_SIGNAL_KEYWORDS = (
    "buy", "sell", "long", "short", "xauusd", "gold", "btc", "nas100",
    "forex", "sl:", "sl ", "tp:", "tp ", "stop loss", "take profit",
    "entry", "open", "signal",
)


def _looks_like_signal(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in _SIGNAL_KEYWORDS)


def _dry_run_message(raw_text: str, source_group: str) -> dict:
    """Run a single message through the pipeline without executing any trade.

    Returns a summary dict:
        {"intent": str, "action": str, "rejection_reasons": list, "extracted": dict|None}
    """
    try:
        from telegram_signal_copier.config import AppConfig
        from telegram_signal_copier.agents.graph import build_graph, run_on_message
        from telegram_signal_copier.agents._llm_shim import SimpleLLM
        from telegram_signal_copier.services.openai_client import OpenAIClient
        from telegram_signal_copier.adapters.bridge import FileBridgeExecutor

        cfg = AppConfig.from_env(ROOT)

        # NullExecutor — same interface as FileBridgeExecutor but never writes
        class _NullExecutor:
            def submit(self, cmd):
                from telegram_signal_copier.models import ExecutionResult
                return ExecutionResult(
                    request_id=cmd.request_id,
                    status="DRY_RUN",
                    order_ticket="DRY_RUN",
                    error_message=None,
                )
            # FileBridgeExecutor attributes used by execution_agent_node
            inbox_dir = ROOT / "bridge" / "inbox"
            outbox_dir = ROOT / "bridge" / "outbox"
            timeout_seconds = 5.0
            symbol_suffix = getattr(cfg, "mt5_symbol_suffix", "m")
            legacy_inbox_mirror_delay_seconds = 0.0

        client = OpenAIClient(cfg)
        llm = SimpleLLM(client)

        # Build executor — we're using the real one but that's OK because
        # the pipeline will only reach "execute" for valid signals; we want
        # to see if they reach that point.
        executor = _NullExecutor()
        graph = build_graph(cfg, llm, executor)
        state = run_on_message(graph, raw_text, source_group=source_group)

        ext = None
        if state.extracted_signal:
            s = state.extracted_signal
            ext = {
                "symbol": s.symbol_raw,
                "side": str(s.side),
                "entry": s.entry_price,
                "sl": s.stop_loss,
                "tps": s.take_profits,
            }
        return {
            "intent": state.intent,
            "action": "OPEN_TRADE" if state.execution_status in ("DRY_RUN", "FILLED", "SUBMITTED") else "REJECTED",
            "rejection_reasons": list(state.rejection_reasons or []),
            "extracted": ext,
        }
    except Exception as exc:
        logger.debug("[DRY_RUN] Error: %s", exc)
        return {"intent": None, "action": "ERROR", "rejection_reasons": [str(exc)], "extracted": None}


def analyse_missed_trades(raw_messages: list[dict], pipeline_entries: list[dict]) -> dict:
    """Cross-reference raw Telegram messages against pipeline outcomes.

    Returns a report dict with:
        not_in_pipeline   — messages received by listener but never processed
        rejected          — pipeline entries with action=REJECTED
        dry_run_results   — dry-run outcomes for not_in_pipeline signal candidates
        rejection_summary — Counter of rejection reason strings
        missed_count      — signals that look like trades but were not executed
    """
    # Build lookup: (source_group, message_id) → pipeline entry
    pipeline_map: dict[tuple[str, str], dict] = {}
    for e in pipeline_entries:
        key = (e.get("source_group", ""), str(e.get("message_id", "")))
        pipeline_map[key] = e

    # Messages received but not in pipeline log
    not_in_pipeline: list[dict] = []
    for msg in raw_messages:
        key = (msg.get("source_group", ""), str(msg.get("message_id", "")))
        if key not in pipeline_map:
            not_in_pipeline.append(msg)

    # Rejected entries (signal reached pipeline but was rejected)
    rejected = [e for e in pipeline_entries if e.get("action_taken") == "REJECTED"]

    # Rejection reason summary
    reason_ctr: Counter[str] = Counter()
    for e in rejected:
        for r in (e.get("rejection_reasons") or []):
            # strip prefix like "RejectionReason.X: ..." → keep just the key
            short = r.split(":")[0].replace("RejectionReason.", "").strip()
            reason_ctr[short] += 1

    # Dry-run signal candidates that were not in pipeline
    dry_run_results: list[dict] = []
    signal_candidates = [m for m in not_in_pipeline if _looks_like_signal(m.get("text", ""))]
    # Limit to 10 dry-runs per cycle to avoid LLM overload
    for msg in signal_candidates[:10]:
        result = _dry_run_message(msg.get("text", ""), msg.get("source_group", ""))
        dry_run_results.append({
            "source_group": msg.get("source_group"),
            "message_id":   msg.get("message_id"),
            "ts":           msg.get("ts"),
            "text_snippet": (msg.get("text") or "")[:120],
            **result,
        })

    # Count missed potential trades (dry-ran as OPEN_TRADE but never in pipeline)
    missed_trades = [r for r in dry_run_results if r.get("action") == "OPEN_TRADE"]

    return {
        "raw_received":       len(raw_messages),
        "not_in_pipeline":    len(not_in_pipeline),
        "signal_candidates":  len(signal_candidates),
        "dry_run_count":      len(dry_run_results),
        "missed_trades":      missed_trades,
        "missed_count":       len(missed_trades),
        "rejected_count":     len(rejected),
        "rejection_summary":  dict(reason_ctr.most_common(10)),
        "dry_run_details":    dry_run_results,
        "not_in_pipeline_samples": [
            {"source_group": m.get("source_group"), "message_id": m.get("message_id"),
             "ts": m.get("ts"), "text": (m.get("text") or "")[:100]}
            for m in not_in_pipeline[:5]
        ],
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

def _emit_report(
    verdict: str,
    reasons: list[str],
    bridge: dict,
    failure,
    actions: list[str],
    retro: dict | None = None,
    rejection_analysis: dict | None = None,
) -> None:
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
    if retro:
        report["retro"] = {
            "raw_received":      retro.get("raw_received", 0),
            "not_in_pipeline":   retro.get("not_in_pipeline", 0),
            "signal_candidates": retro.get("signal_candidates", 0),
            "missed_count":      retro.get("missed_count", 0),
            "rejected_count":    retro.get("rejected_count", 0),
            "rejection_summary": retro.get("rejection_summary", {}),
            "missed_trades":     retro.get("missed_trades", []),
        }
    if rejection_analysis:
        report["rejection_analysis"] = {
            "rejected_count":    rejection_analysis.get("rejected_count", 0),
            "fp_reports":        rejection_analysis.get("fp_reports", []),
            "fixed_categories":  rejection_analysis.get("fixed_categories", []),
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
    logger.info(
        "Smart Supervisor started. interval=%ds fix=%s retro=%s rejection_check=%s",
        args.interval, not args.no_fix, not args.no_retro, not args.no_rejection_check,
    )
    logger.info("Pipeline logs: %s", LOGS_DIR)
    logger.info("Bridge root:   %s", BRIDGE_ROOT)

    report_interval = args.report_interval
    _last_retro_ts: float = 0.0
    _last_rejection_check_ts: float = 0.0

    while True:
        loop_start = time.time()
        actions: list[str] = []
        retro_report: dict | None = None
        rejection_report: dict | None = None

        # 1. Read pipeline logs
        recent_logs = _read_recent_pipeline_logs(n=args.sample_window)

        # 2. Bridge health
        bridge = _bridge_health()

        # 3. Classify failures (pipeline-log-based)
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

        # 7. Retrospective Telegram message analysis (periodic, default 1 h)
        now = time.time()
        if (now - _last_retro_ts) >= args.retro_interval and not args.no_retro:
            raw_msgs = _read_raw_messages(n=args.retro_messages)
            if raw_msgs:
                logger.info("[RETRO] Analysing %d raw messages vs %d pipeline entries…",
                            len(raw_msgs), len(recent_logs))
                retro_report = analyse_missed_trades(raw_msgs, recent_logs)
                _last_retro_ts = now

                missed = retro_report.get("missed_trades", [])
                if missed:
                    logger.warning("[RETRO] %d potential missed trade(s) detected!", len(missed))
                    for m in missed:
                        logger.warning(
                            "[RETRO]   group=%s msg=%s intent=%s extract=%s  snippet: %s",
                            m.get("source_group", "?"), m.get("message_id", "?"),
                            m.get("intent", "?"), m.get("extracted"),
                            (m.get("text_snippet") or "")[:80],
                        )
                    actions.append(f"retro_missed={len(missed)}")
                    if not args.no_fix:
                        _retro_fix_missed(missed, state, args)

                rr = retro_report.get("rejection_summary", {})
                if rr:
                    logger.info("[RETRO] Rejection reasons (last %d msgs): %s",
                                args.retro_messages, rr)
                not_proc = retro_report.get("not_in_pipeline", 0)
                if not_proc:
                    logger.info("[RETRO] %d message(s) never reached pipeline", not_proc)
            else:
                logger.debug("[RETRO] No raw message log yet — skipping")
                _last_retro_ts = now

        # 8. Rejection false-positive analysis (periodic, default 30 min)
        if (now - _last_rejection_check_ts) >= args.rejection_interval and not args.no_rejection_check:
            rejection_report = _analyse_rejections(recent_logs, state, args)
            _last_rejection_check_ts = now
            fp_fixed = rejection_report.get("fixed_categories", [])
            if fp_fixed:
                actions.append(f"fp_fix={'|'.join(fp_fixed)}")
            fp_count = sum(
                1 for r in rejection_report.get("fp_reports", [])
                if r.get("verdict") == "FALSE_POSITIVE"
            )
            if fp_count:
                actions.append(f"false_positives_detected={fp_count}")

        # 9. Compute verdict
        now2 = time.time()
        verdict, reasons = _compute_verdict(bridge, failure)

        # 10. Emit report at report_interval
        if now2 - state.last_report_ts >= report_interval or verdict != state.last_verdict:
            _emit_report(verdict, reasons, bridge, failure, actions, retro_report, rejection_report)
            state.last_report_ts = now2
            if verdict != state.last_verdict:
                state.last_verdict = verdict

        # Sleep remainder of interval
        elapsed = time.time() - loop_start
        sleep_time = max(0.5, args.interval - elapsed)
        time.sleep(sleep_time)


def _retro_fix_missed(missed_trades: list[dict], state: "SupervisorState", args) -> None:
    """Synthesize a FailureReport from retrospective missed trades and attempt a fix."""
    from telegram_signal_copier.agents.developer_agent import FailureReport, _try_fix_report  # noqa: F401

    # Group by likely root cause
    cause_count: dict[str, int] = Counter()
    examples: list[str] = []
    for m in missed_trades:
        intent = m.get("intent") or "UNKNOWN"
        reasons = m.get("rejection_reasons") or []
        cause = reasons[0] if reasons else f"INTENT_{intent}"
        cause_count[cause] += 1
        if len(examples) < 5:
            examples.append(m.get("text_snippet", "")[:200])

    if not cause_count:
        return

    top_cause, top_count = cause_count.most_common(1)[0]
    logger.info("[RETRO] Top failure cause: %s (%d misses)", top_cause, top_count)

    # Build a lightweight FailureReport and delegate to the normal fix pathway
    try:
        from telegram_signal_copier.agents.developer_agent import (
            FailureReport, generate_patch, apply_patch
        )
        from telegram_signal_copier.services.openai_client import OpenAIClient
        from telegram_signal_copier.config import AppConfig

        cfg = AppConfig.from_env(ROOT)
        llm = OpenAIClient(cfg)

        synthetic_logs = [
            {
                "intent": m.get("intent", "UNKNOWN"),
                "action_taken": m.get("action"),
                "rejection_reasons": m.get("rejection_reasons", []),
                "text_snippet": m.get("text_snippet", ""),
                "source_group": m.get("source_group", ""),
            }
            for m in missed_trades
        ]
        report = FailureReport(
            category=top_cause,
            count=top_count,
            examples=examples,
            raw_logs=synthetic_logs,
        )
        if top_cause in state.post_fix_watch:
            logger.info("[RETRO] Cause %s already under post-fix watch — skipping", top_cause)
            return
        if state.fixes_this_session >= 10:
            logger.warning("[RETRO] Max fixes/session reached — skipping retro fix")
            return

        patch = generate_patch(report, ROOT, llm)
        if patch:
            ok = apply_patch(patch, ROOT)
            if ok:
                state.fixes_this_session += 1
                state.post_fix_watch[top_cause] = time.time()
                logger.info("[RETRO] Patch applied for %s", top_cause)
            else:
                logger.warning("[RETRO] Patch apply failed for %s", top_cause)
        else:
            logger.info("[RETRO] Developer agent produced no patch for %s", top_cause)
    except Exception as exc:
        logger.warning("[RETRO] _retro_fix_missed error: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# Rejection analysis — false-positive detector
# ══════════════════════════════════════════════════════════════════════════════

def _analyse_rejections(
    recent_logs: list[dict],
    state: "SupervisorState",
    args,
) -> dict:
    """Analyse rejected pipeline log entries to find false-positive rejections.

    Workflow:
    1. Extract all entries where action_taken == REJECTED
    2. Group by primary rejection reason
    3. For each group, ask the LLM: "is this rule over-strict?"
    4. For confirmed false positives, generate + apply a code fix
    5. Return a structured report

    Returns dict with keys: rejected_count, fp_reports, fixed_categories, errors
    """
    result = {
        "rejected_count": 0,
        "fp_reports": [],
        "fixed_categories": [],
        "errors": [],
    }

    try:
        from telegram_signal_copier.agents.developer_agent import (
            assess_false_positives, fix_false_positives,
        )
        from telegram_signal_copier.services.openai_client import OpenAIClient
        from telegram_signal_copier.config import AppConfig

        rejected = [e for e in recent_logs if e.get("action_taken") == "REJECTED"]
        result["rejected_count"] = len(rejected)

        if not rejected:
            logger.info("[REJECTION_ANALYSIS] No rejected entries in last %d log records", len(recent_logs))
            return result

        logger.info(
            "[REJECTION_ANALYSIS] Analysing %d rejected signals for false positives…", len(rejected)
        )

        # Group rejections for readable log output
        from collections import Counter
        reason_ctr: Counter[str] = Counter()
        for e in rejected:
            for r in (e.get("rejection_reasons") or []):
                short = r.split(":")[0].replace("RejectionReason.", "").strip()
                reason_ctr[short] += 1
        if reason_ctr:
            logger.info("[REJECTION_ANALYSIS] Rejection breakdown: %s", dict(reason_ctr.most_common(10)))

        cfg = AppConfig.from_env(ROOT)
        llm = OpenAIClient(cfg)

        fp_reports = assess_false_positives(
            rejected_entries=rejected,
            repo_root=ROOT,
            llm_client=llm,
            min_count=args.rejection_min_count,
        )

        for fp in fp_reports:
            logger.info(
                "[REJECTION_ANALYSIS] %s → verdict=%s count=%d  %s",
                fp.rejection_reason, fp.verdict, fp.count, fp.llm_reasoning[:100],
            )
            if fp.verdict == "FALSE_POSITIVE" and fp.suggested_fix:
                logger.warning(
                    "[REJECTION_ANALYSIS] FALSE POSITIVE DETECTED: '%s' is incorrectly blocking "
                    "valid trades. Suggested fix: %s",
                    fp.rejection_reason, fp.suggested_fix,
                )

        result["fp_reports"] = [
            {
                "rejection_reason": fp.rejection_reason,
                "verdict": fp.verdict,
                "count": fp.count,
                "reasoning": fp.llm_reasoning,
                "suggested_fix": fp.suggested_fix,
                "examples": fp.examples[:2],
            }
            for fp in fp_reports
        ]

        if not args.no_fix:
            fixed = fix_false_positives(
                fp_reports=fp_reports,
                repo_root=ROOT,
                llm_client=llm,
                session_state=state,
            )
            result["fixed_categories"] = fixed
            if fixed:
                logger.info("[REJECTION_ANALYSIS] Fixed false-positive rules: %s", fixed)
                # Restart listener to pick up patched validation
                _restart_listener()

    except Exception as exc:
        logger.warning("[REJECTION_ANALYSIS] Error: %s", exc)
        result["errors"].append(str(exc))

    return result


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
    parser.add_argument("--interval",           type=int,   default=30,   help="Check interval in seconds (default: 30)")
    parser.add_argument("--sample-window",       type=int,   default=50,   help="Number of recent pipeline log entries to analyse (default: 50)")
    parser.add_argument("--min-failures",        type=int,   default=3,    help="Minimum failure count to trigger a fix (default: 3)")
    parser.add_argument("--report-interval",     type=int,   default=60,   help="Seconds between report lines when verdict unchanged (default: 60)")
    parser.add_argument("--no-fix",              action="store_true",      help="Disable code fixing (monitor only)")
    parser.add_argument("--retro-interval",      type=int,   default=3600, help="Seconds between Telegram retro analyses (default: 3600 = 1h)")
    parser.add_argument("--retro-messages",      type=int,   default=200,  help="Number of recent Telegram messages to scan per retro (default: 200)")
    parser.add_argument("--no-retro",            action="store_true",      help="Disable retrospective Telegram message analysis")
    parser.add_argument("--rejection-interval",  type=int,   default=1800, help="Seconds between rejection false-positive checks (default: 1800 = 30 min)")
    parser.add_argument("--rejection-min-count", type=int,   default=2,    help="Min rejection count per reason to trigger FP assessment (default: 2)")
    parser.add_argument("--no-rejection-check",  action="store_true",      help="Disable rejection false-positive analysis")
    args = parser.parse_args()

    try:
        run(args)
    except KeyboardInterrupt:
        logger.info("Smart Supervisor stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
