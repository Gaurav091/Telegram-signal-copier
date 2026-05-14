from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
HEARTBEAT_STALE_SEC = 120
DEFAULT_INTERVAL_SEC = 10
DEFAULT_ACTIVITY_WINDOW_SEC = 300
DEFAULT_NO_UPDATE_BLOCK_SEC = 180
DEFAULT_RESTART_COOLDOWN_SEC = 120
DEFAULT_STALE_CMD_SEC = 120
DEFAULT_REPORT_INTERVAL_SEC = 60

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = WORKSPACE_ROOT / "logs"
BRIDGE_ROOT = Path(__import__("os").environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal" / "Common" / "Files" / "TelegramSignalCopierBridge"
EA_STATUS = BRIDGE_ROOT / "ea_status.txt"
TG_STATUS = BRIDGE_ROOT / "telegram_status.txt"
OUTBOX = BRIDGE_ROOT / "outbox"


def _now_epoch() -> float:
    return time.time()


def _now_utc_str() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _read_kv(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    except Exception:
        return {}


def _age_from_epoch(epoch_str: str | None) -> float:
    if not epoch_str:
        return float("inf")
    try:
        return _now_epoch() - float(epoch_str)
    except Exception:
        return float("inf")


def _tail_text(path: Path, max_bytes: int = 2_000_000) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
        for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
            try:
                return data.decode(enc, errors="ignore")
            except Exception:
                continue
    except Exception:
        return ""
    return ""


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    depth = 0
    start = -1
    in_str = False
    esc = False

    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
            continue

        if ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start != -1:
                raw = text[start : i + 1]
                start = -1
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict):
                        blocks.append(obj)
                except Exception:
                    continue

    return blocks


def _parse_log_ts(line: str) -> float | None:
    # Example: 2026-05-14 09:07:44,407 [INFO] ...
    if len(line) < 23:
        return None
    prefix = line[:23]
    try:
        dt = datetime.strptime(prefix, "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=UTC)
        return dt.timestamp()
    except Exception:
        return None


def _latest_listener_log() -> Path:
    p = LOGS_DIR / "listener-restart.log"
    return p


@dataclass
class Snapshot:
    ts: float
    tg_age: float
    ea_age: float
    listener_state: str
    last_message_id: str
    last_message_change_age: float
    last_decision: str
    last_execution_status: str
    cmd_pending: int
    cmd_stale: int
    result_count_recent: int
    updates_recent: int
    updates_last_age: float
    ai_fail_recent: int
    ai_vision_fail_recent: int


class Supervisor:
    def __init__(
        self,
        interval_sec: int,
        activity_window_sec: int,
        no_update_block_sec: int,
        restart_cooldown_sec: int,
        stale_cmd_sec: int,
        report_interval_sec: int,
        autofix: bool,
    ) -> None:
        self.interval_sec = max(3, interval_sec)
        self.activity_window_sec = max(30, activity_window_sec)
        self.no_update_block_sec = max(30, no_update_block_sec)
        self.restart_cooldown_sec = max(30, restart_cooldown_sec)
        self.stale_cmd_sec = max(30, stale_cmd_sec)
        self.report_interval_sec = max(10, report_interval_sec)
        self.autofix = autofix

        self.started_at = _now_epoch()
        self.last_restart_ts = 0.0
        self.last_report_ts = 0.0
        self.reason_counts: Counter[str] = Counter()

        self._last_seen_message_id = ""
        self._last_msg_change_ts = self.started_at

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.daily_report = LOGS_DIR / f"workflow_supervisor_{datetime.now(tz=UTC).strftime('%Y-%m-%d')}.jsonl"
        self.actions_log = LOGS_DIR / "workflow_supervisor_actions.log"

    def _log_action(self, msg: str) -> None:
        line = f"[{_now_utc_str()}] {msg}\n"
        print(line.strip(), flush=True)
        try:
            with self.actions_log.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def _restart_listener(self) -> tuple[bool, str]:
        cmd = [str(WORKSPACE_ROOT / ".venv" / "Scripts" / "python.exe"), str(WORKSPACE_ROOT / "tools" / "restart_listener.py")]
        try:
            r = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=90)
            out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
            if r.returncode == 0:
                return True, out
            return False, out
        except Exception as exc:
            return False, str(exc)

    def _collect_snapshot(self) -> Snapshot:
        tg = _read_kv(TG_STATUS)
        ea = _read_kv(EA_STATUS)

        tg_age = _age_from_epoch(tg.get("heartbeat_epoch"))
        ea_age = _age_from_epoch(ea.get("heartbeat_epoch"))
        listener_state = tg.get("listener_state", "unknown")
        last_message_id = str(tg.get("last_message_id", "") or "")
        last_decision = str(tg.get("last_decision", "") or "")
        last_execution_status = str(tg.get("last_execution_status", "") or "")

        if last_message_id and last_message_id != self._last_seen_message_id:
            self._last_seen_message_id = last_message_id
            self._last_msg_change_ts = _now_epoch()

        now = _now_epoch()
        cmd_files = sorted(BRIDGE_ROOT.glob("*.cmd"), key=lambda p: p.stat().st_mtime)
        cmd_pending = len(cmd_files)
        cmd_stale = len([p for p in cmd_files if now - p.stat().st_mtime > self.stale_cmd_sec])

        result_files = sorted(OUTBOX.glob("*.result"), key=lambda p: p.stat().st_mtime, reverse=True)
        result_count_recent = len([p for p in result_files if now - p.stat().st_mtime <= self.activity_window_sec])

        log_text = _tail_text(_latest_listener_log())
        lines = log_text.splitlines()

        updates_recent = 0
        latest_update_ts = 0.0
        for line in lines:
            if "Got difference for channel" not in line:
                continue
            ts = _parse_log_ts(line)
            if ts is None:
                continue
            latest_update_ts = max(latest_update_ts, ts)
            if now - ts <= self.activity_window_sec:
                updates_recent += 1

        updates_last_age = float("inf") if latest_update_ts <= 0 else now - latest_update_ts

        ai_fail_recent = 0
        ai_vision_fail_recent = 0
        for line in lines:
            ts = _parse_log_ts(line)
            if ts is None or (now - ts) > self.activity_window_sec:
                continue
            low = line.lower()
            if "ai parse failed" in low:
                ai_fail_recent += 1
            if "ai vision failed" in low:
                ai_vision_fail_recent += 1

        return Snapshot(
            ts=now,
            tg_age=tg_age,
            ea_age=ea_age,
            listener_state=listener_state,
            last_message_id=last_message_id,
            last_message_change_age=max(0.0, now - self._last_msg_change_ts),
            last_decision=last_decision,
            last_execution_status=last_execution_status,
            cmd_pending=cmd_pending,
            cmd_stale=cmd_stale,
            result_count_recent=result_count_recent,
            updates_recent=updates_recent,
            updates_last_age=updates_last_age,
            ai_fail_recent=ai_fail_recent,
            ai_vision_fail_recent=ai_vision_fail_recent,
        )

    def _evaluate(self, s: Snapshot) -> tuple[str, list[str]]:
        verdict = "HEALTHY"
        reasons: list[str] = []

        if s.tg_age > HEARTBEAT_STALE_SEC or s.listener_state in {"error", "stopped"}:
            verdict = "BLOCKED"
            reasons.append("telegram listener stale/offline")

        if s.last_message_id and s.last_message_change_age > self.no_update_block_sec and s.updates_last_age > self.no_update_block_sec:
            if verdict == "HEALTHY":
                verdict = "DEGRADED"
            reasons.append("no new telegram messages in recent window (idle)")

        if s.ea_age > HEARTBEAT_STALE_SEC:
            verdict = "BLOCKED"
            reasons.append("mt5 ea heartbeat stale")

        if s.cmd_stale > 0:
            verdict = "BLOCKED"
            reasons.append(f"{s.cmd_stale} stale command(s) waiting for mt5")

        if s.last_decision.upper() == "APPROVED" and s.last_execution_status.upper() == "TIMEOUT" and s.last_message_change_age <= self.activity_window_sec:
            if verdict == "HEALTHY":
                verdict = "DEGRADED"
            reasons.append("latest approved signal timed out waiting for mt5 result")

        if s.ai_fail_recent > 0:
            if verdict == "HEALTHY":
                verdict = "DEGRADED"
            reasons.append(f"ai parse fallback count={s.ai_fail_recent}")

        return verdict, reasons

    def _maybe_fix(self, s: Snapshot, verdict: str, reasons: list[str]) -> list[str]:
        actions: list[str] = []
        now = _now_epoch()

        should_restart_listener = (
            ("telegram listener stale/offline" in reasons)
            or ("no new telegram messages in recent window (idle)" in reasons and s.listener_state != "running")
        )

        if self.autofix and should_restart_listener and (now - self.last_restart_ts) >= self.restart_cooldown_sec:
            ok, detail = self._restart_listener()
            self.last_restart_ts = now
            if ok:
                msg = "autofix: restarted listener"
                actions.append(msg)
                self._log_action(msg)
            else:
                msg = f"autofix_failed: restart listener failed ({detail[:300]})"
                actions.append(msg)
                self._log_action(msg)

        return actions

    def _report(self, s: Snapshot, verdict: str, reasons: list[str], actions: list[str]) -> None:
        for r in reasons:
            self.reason_counts[r] += 1

        row = {
            "ts": _now_utc_str(),
            "uptime_s": round(_now_epoch() - self.started_at, 1),
            "verdict": verdict,
            "reasons": reasons,
            "actions": actions,
            "reason_totals": dict(self.reason_counts),
            "telegram": {
                "listener_state": s.listener_state,
                "heartbeat_age_s": round(s.tg_age, 1) if s.tg_age != float("inf") else None,
                "updates_recent": s.updates_recent,
                "updates_last_age_s": round(s.updates_last_age, 1) if s.updates_last_age != float("inf") else None,
            },
            "parser": {
                "last_message_id": s.last_message_id,
                "last_message_change_age_s": round(s.last_message_change_age, 1),
                "last_decision": s.last_decision,
                "last_execution_status": s.last_execution_status,
                "ai_fail_recent": s.ai_fail_recent,
                "ai_vision_fail_recent": s.ai_vision_fail_recent,
            },
            "bridge": {
                "pending_cmd": s.cmd_pending,
                "stale_cmd": s.cmd_stale,
                "result_recent": s.result_count_recent,
            },
            "mt5": {
                "heartbeat_age_s": round(s.ea_age, 1) if s.ea_age != float("inf") else None,
                "latest_execution_status": s.last_execution_status,
                "result_recent": s.result_count_recent,
            },
        }

        print(json.dumps(row), flush=True)

        if _now_epoch() - self.last_report_ts >= self.report_interval_sec:
            try:
                with self.daily_report.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
            except Exception:
                pass
            self.last_report_ts = _now_epoch()

    def run(self) -> None:
        print(f"Workflow supervisor ON interval={self.interval_sec}s autofix={self.autofix}")
        print(f"Workspace: {WORKSPACE_ROOT}")
        print(f"Bridge: {BRIDGE_ROOT}")
        print("Ctrl+C to stop")

        while True:
            snap = self._collect_snapshot()
            verdict, reasons = self._evaluate(snap)
            actions = self._maybe_fix(snap, verdict, reasons)
            self._report(snap, verdict, reasons, actions)
            time.sleep(self.interval_sec)


def main() -> None:
    parser = argparse.ArgumentParser(description="Top-level workflow supervisor")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SEC)
    parser.add_argument("--activity-window-sec", type=int, default=DEFAULT_ACTIVITY_WINDOW_SEC)
    parser.add_argument("--no-update-block-sec", type=int, default=DEFAULT_NO_UPDATE_BLOCK_SEC)
    parser.add_argument("--restart-cooldown-sec", type=int, default=DEFAULT_RESTART_COOLDOWN_SEC)
    parser.add_argument("--stale-cmd-sec", type=int, default=DEFAULT_STALE_CMD_SEC)
    parser.add_argument("--report-interval-sec", type=int, default=DEFAULT_REPORT_INTERVAL_SEC)
    parser.add_argument("--no-autofix", action="store_true")
    args = parser.parse_args()

    sup = Supervisor(
        interval_sec=args.interval,
        activity_window_sec=args.activity_window_sec,
        no_update_block_sec=args.no_update_block_sec,
        restart_cooldown_sec=args.restart_cooldown_sec,
        stale_cmd_sec=args.stale_cmd_sec,
        report_interval_sec=args.report_interval_sec,
        autofix=not args.no_autofix,
    )
    sup.run()


if __name__ == "__main__":
    main()
