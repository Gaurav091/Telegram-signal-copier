# Workflow Supervisor — Autonomous Agent Monitoring & Auto-Recovery

Complete end-to-end workflow supervisor agent that continuously monitors the entire signal copier pipeline and auto-fixes issues.

## What It Monitors

```
┌─────────────────────────────────────────────────────────────┐
│                    WORKFLOW SUPERVISOR                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  TELEGRAM        PARSER/AI         BRIDGE           MT5 EA   │
│  ─────────       ──────────        ──────           ──────   │
│  • Listener      • Extraction      • Command        • Heart  │
│    heartbeat     • Confidence        queue           beat    │
│  • Message       • AI success/      • Stale cmds    • Exec   │
│    receipt         fail            • Result file     status  │
│  • Update        • Decision          health         • Filled │
│    rate          • Intent                            trades  │
│                  • Vision parse                              │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Per-Component Checks

**Telegram Listener**
- Heartbeat age (should be < 120s)
- Recent message arrivals
- Listener state (running/error/stopped)

**Parser & AI**
- Last message ID progression (detects stuck messages)
- Confidence level tracking
- AI provider failures (text + vision)
- Decision status (APPROVED/REJECTED/SKIPPED)

**Bridge Queue**
- Command file age (should be < 120s)
- Result file arrival rate
- Queue backlog detection

**MT5 EA**
- Heartbeat presence (should be < 120s)
- Execution status (EXECUTED, TIMEOUT, etc.)
- Trade result file writing

## Output Verdicts

| Verdict | Meaning | Auto-Fix Action |
|---------|---------|-----------------|
| `HEALTHY` | All systems OK, no issues | None (idle monitoring) |
| `DEGRADED` | Issue detected, but components alive | Attempt listener restart |
| `BLOCKED` | Critical issue, workflow broken | Listener restart + logging |
| `RECOVERING` | Was broken, now recovering | Wait for stability window |

## Usage

### Default (Auto-Fix Enabled)
```bash
# Production-safe: monitors + auto-restarts listener on failure
python tools/supervisor_start.py

# Or direct:
python tools/workflow_supervisor.py --interval 10
```

Output is logged to:
- `logs/workflow_supervisor_2026-05-14.jsonl` (daily JSON lines)
- `logs/workflow_supervisor_actions.log` (auto-fix events)

### Monitor-Only (No Auto-Fix)
```bash
python tools/supervisor_start.py --no-autofix
# Or:
python tools/workflow_supervisor.py --interval 10 --no-autofix
```

### Custom Thresholds
```bash
# Slower checks, wider idle window
python tools/supervisor_start.py --interval 15 --no-update-block-sec 300

# Faster checks for high-frequency signal sources
python tools/supervisor_start.py --interval 5 --no-update-block-sec 60 --stale-cmd-sec 60
```

## JSON Output Format

Each output line is valid JSON with full workflow state:

```json
{
  "ts": "2026-05-14 10:30:15 UTC",
  "uptime_s": 3600.5,
  "verdict": "HEALTHY",
  "reasons": [],
  "actions": [],
  "reason_totals": {},
  
  "telegram": {
    "listener_state": "running",
    "heartbeat_age_s": 1.3,
    "updates_recent": 2,
    "updates_last_age_s": 42.1
  },
  
  "parser": {
    "last_message_id": "8204",
    "last_message_change_age_s": 0.0,
    "last_decision": "APPROVED",
    "last_execution_status": "EXECUTED",
    "ai_fail_recent": 0,
    "ai_vision_fail_recent": 0
  },
  
  "bridge": {
    "pending_cmd": 1,
    "stale_cmd": 0,
    "result_recent": 1
  },
  
  "mt5": {
    "heartbeat_age_s": 1.2,
    "latest_execution_status": "EXECUTED",
    "result_recent": 1
  }
}
```

## Configuration Defaults

| Option | Default | Description |
|--------|---------|-------------|
| `--interval` | 10s | Check frequency |
| `--activity-window-sec` | 300s | Recent activity lookback |
| `--no-update-block-sec` | 180s | Idle message timeout |
| `--restart-cooldown-sec` | 120s | Min seconds between restarts |
| `--stale-cmd-sec` | 120s | Command age before stale |
| `--no-autofix` | false | Disable auto-remediation |

## Degradation Triggers

The supervisor marks system as DEGRADED or BLOCKED when:

1. **No new messages** — Last message unchanged for > `--no-update-block-sec`
2. **Listener offline** — Heartbeat stale (> 120s) or state=error
3. **Stale bridge commands** — Commands waiting > `--stale-cmd-sec`
4. **Latest trade timeout** — Approved signal executed but timed out
5. **Recent AI failures** — Text or vision parse failures in recent window
6. **Multiple EA instances** — Multiple charts with same EA (degraded, not blocked)
7. **MT5 EA offline** — Heartbeat missing or stale

## Auto-Fix Actions

When `--autofix` is enabled (default):

1. **Listener Restart** — If listener offline or stuck without messages
   - Cooldown: 120s between attempts
   - Safe: no trade commands injected
   - Logged: `logs/workflow_supervisor_actions.log`

2. **Stale Temp File Cleanup** — Removes old smoke-test `.cmd` files > 10 min old

3. **Non-Invasive** — Never:
   - Kills or cancels trades
   - Modifies MT5 data
   - Injects fake signals
   - Resets configuration

## Running Alongside Bridge Monitor

Both tools can run simultaneously for comprehensive observability:

```bash
# Terminal 1: High-level workflow supervision (auto-fix)
python tools/supervisor_start.py --interval 10

# Terminal 2: Low-level bridge queue monitoring (visual UI)
python tools/bridge_monitor.py
```

Or with agent mode for both:

```bash
# Terminal 1: Workflow supervisor
python tools/workflow_supervisor.py --interval 10 &

# Terminal 2: Bridge monitor agent
python tools/bridge_monitor.py --agent --interval 5
```

## Interpreting Results

### HEALTHY → Message Arrives
```json
{
  "verdict": "HEALTHY",
  "reasons": [],
  "telegram": {"heartbeat_age_s": 1.1},
  "parser": {"last_message_id": "8204", "last_decision": "APPROVED"},
  "mt5": {"latest_execution_status": "EXECUTED"}
}
```
✓ Normal operation. Message received, parsed, approved, and executed in MT5.

### DEGRADED → AI Failures
```json
{
  "verdict": "DEGRADED",
  "reasons": ["ai parse fallback count=3"],
  "parser": {"ai_fail_recent": 3, "ai_vision_fail_recent": 1}
}
```
⚠ Some messages failing to parse. Text-only fallback used. Check provider quotas.

### DEGRADED → Idle Timeout
```json
{
  "verdict": "DEGRADED",
  "reasons": ["no new telegram messages in recent window (idle)"],
  "parser": {"last_message_change_age_s": 245.0}
}
```
ℹ No new messages for 4+ minutes. Expected if signal source is quiet.

### BLOCKED → Listener Offline
```json
{
  "verdict": "BLOCKED",
  "reasons": ["telegram listener stale/offline"],
  "actions": ["autofix: restarted listener"],
  "telegram": {"listener_state": "error", "heartbeat_age_s": null}
}
```
✗ Listener crashed. Auto-fix attempted restart.

### BLOCKED → Stale Commands
```json
{
  "verdict": "BLOCKED",
  "reasons": ["1 stale command(s) waiting for mt5"],
  "bridge": {"stale_cmd": 1, "pending_cmd": 1}
}
```
✗ Command sent to MT5 but not consumed. Check:
- MT5 EA attached to chart
- Algo Trading enabled (green button)
- Check MT5 Expert tab for errors

## Log Files

### `logs/workflow_supervisor_2026-05-14.jsonl`
One JSON object per line, appended every 60s (configurable).

```bash
# Tail live verdicts
tail -f logs/workflow_supervisor_2026-05-14.jsonl | jq '.verdict'

# Count verdict types
tail -100 logs/workflow_supervisor_2026-05-14.jsonl | jq '.verdict' | sort | uniq -c

# Find all BLOCKED events
grep '"verdict":"BLOCKED"' logs/workflow_supervisor_2026-05-14.jsonl | jq '.reasons'
```

### `logs/workflow_supervisor_actions.log`
Human-readable log of all auto-fix actions:

```
[2026-05-14 10:30:15 UTC] autofix: restarted listener
[2026-05-14 10:30:45 UTC] listener restart attempted: success
[2026-05-14 10:31:10 UTC] removed 2 stale smoke cmd file(s)
```

## Performance & Overhead

- CPU: < 1% (poll-based, no busy loops)
- Memory: ~20MB
- I/O: 5-10 small file reads per check (status files, logs)
- Network: None (local monitoring only)

Recommended for 24/7 operation without performance impact.

## Troubleshooting

**Q: Supervisor reports HEALTHY but bridge has stale commands**
- A: Status files may not be in sync. Check bridge monitor for detailed queue view.

**Q: Auto-fix keeps restarting listener**
- A: Check why listener is crashing in `logs/listener-restart.log`. Usually due to:
  - Telegram session issue (re-run `python -m telegram_signal_copier login`)
  - Network timeout (check internet/DNS)
  - Corrupted session file (delete `.session` files, re-login)

**Q: DEGRADED but no obvious issues**
- A: Check `reason_totals` counter. May be old AI failures that are no longer happening. Wait for stability window to return to HEALTHY.

**Q: Want to disable auto-fix but keep monitoring**
- A: Use `--no-autofix` flag. System will still report issues but won't attempt restarts.

## Integration with Systemd/Task Scheduler

### Windows (Task Scheduler)
```batch
# Create scheduled task
schtasks /create /tn "TelegramSignalCopier-Supervisor" ^
  /tr "python D:\path\to\tools\supervisor_start.py" ^
  /sc onstart /ru SYSTEM /rl HIGHEST /f
```

### Linux/macOS (systemd)
```ini
[Unit]
Description=Telegram Signal Copier Workflow Supervisor
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/workspace
ExecStart=/path/to/.venv/bin/python tools/supervisor_start.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable:
```bash
sudo systemctl enable telegram-signal-copier-supervisor
sudo systemctl start telegram-signal-copier-supervisor
sudo journalctl -u telegram-signal-copier-supervisor -f
```

---

**Version**: 1.0 (2026-05-14)  
**Status**: Production-ready with auto-recovery  
**Last Updated**: May 2026
