"""Analyze R:R from pipeline JSONL logs (parsed SL/TP at signal time).

Unlike MT5 deal history, pipeline logs capture the *intended* SL and TP
at the moment the signal was parsed — before any early exits or partial fills.
This gives accurate R:R ratios for evaluating signal quality.
"""
import json
import glob
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 21

cutoff = datetime.now(tz=timezone.utc) - timedelta(days=DAYS)

# Accumulators per source group
groups: dict[str, dict] = defaultdict(lambda: {
    "signals": 0,
    "filled": 0,
    "rejected": 0,
    "rr_values": [],       # planned R:R ratios
    "profits": [],         # actual P&L if available
    "has_sl": 0,
    "has_tp": 0,
    "has_both": 0,
})

for fpath in sorted(glob.glob(str(LOGS_DIR / "pipeline_*.jsonl"))):
    with open(fpath, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts_str = rec.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if ts < cutoff:
                continue

            src = rec.get("source_group", "UNKNOWN")
            action = rec.get("action_taken", "IGNORE")
            g = groups[src]
            g["signals"] += 1

            if action == "OPEN_TRADE":
                g["filled"] += 1
            elif action == "REJECTED":
                g["rejected"] += 1

            # Extract SL/TP from extraction or validation block
            ext = rec.get("extraction") or {}
            val = rec.get("validation") or {}

            sl = val.get("stop_loss") or ext.get("stop_loss")
            tps = val.get("take_profits") or ext.get("take_profits") or []
            entry = val.get("entry_price") or ext.get("entry_price")
            side = val.get("side") or ext.get("side")

            if sl is not None:
                g["has_sl"] += 1
            if tps:
                g["has_tp"] += 1
            if sl is not None and tps:
                g["has_both"] += 1

            # Calculate planned R:R
            if entry and sl and tps and side:
                risk = abs(float(entry) - float(sl))
                if risk > 0:
                    # Use farthest TP for best-case R:R
                    best_tp = max(abs(float(tp) - float(entry)) for tp in tps)
                    rr = best_tp / risk
                    g["rr_values"].append(rr)

# ── Output ────────────────────────────────────────────────────────────────────
print(f"=== SIGNAL QUALITY ANALYSIS (Pipeline Logs) — Last {DAYS} Days ===")
print(f"({cutoff.strftime('%b %d')} - {datetime.now(tz=timezone.utc).strftime('%b %d, %Y')})")
print()
print(f"{'Group':<30} {'Signals':>7} {'Filled':>6} {'Rej%':>5} {'HasSL':>5} {'HasTP':>5} {'AvgRR':>6} {'MedRR':>6} {'MinRR':>6}")
print("-" * 90)

ranked = sorted(groups.items(), key=lambda x: x[1]["signals"], reverse=True)
for name, g in ranked:
    if g["signals"] < 2:
        continue
    rej_pct = g["rejected"] / g["signals"] * 100
    rrs = g["rr_values"]
    avg_rr = sum(rrs) / len(rrs) if rrs else 0
    med_rr = sorted(rrs)[len(rrs) // 2] if rrs else 0
    min_rr = min(rrs) if rrs else 0
    marker = " ✓" if avg_rr >= 1.0 and g["filled"] > 0 else ""
    print(
        f"{name:<30} {g['signals']:>7} {g['filled']:>6} {rej_pct:>4.0f}% "
        f"{g['has_sl']:>5} {g['has_tp']:>5} "
        f"{avg_rr:>5.1f}:1 {med_rr:>5.1f}:1 {min_rr:>5.1f}:1{marker}"
    )

print("-" * 90)
total_signals = sum(g["signals"] for _, g in ranked)
total_filled = sum(g["filled"] for _, g in ranked)
print(f"{'TOTAL':<30} {total_signals:>7} {total_filled:>6}")

# ── Groups meeting criteria ───────────────────────────────────────────────────
print()
print("=== GROUPS WITH AVG R:R >= 1:1 AND FILLED TRADES ===")
print(f"{'Group':<30} {'Filled':>6} {'AvgRR':>6} {'MedRR':>6} {'Signals':>7} {'HasBoth%':>8}")
print("-" * 70)
qualifying = []
for name, g in ranked:
    rrs = g["rr_values"]
    if not rrs or g["filled"] == 0:
        continue
    avg_rr = sum(rrs) / len(rrs)
    if avg_rr >= 1.0:
        med_rr = sorted(rrs)[len(rrs) // 2]
        both_pct = g["has_both"] / g["signals"] * 100
        qualifying.append((name, g["filled"], avg_rr, med_rr, g["signals"], both_pct))

if qualifying:
    for name, filled, avg_rr, med_rr, signals, both_pct in sorted(qualifying, key=lambda x: x[2], reverse=True):
        print(f"{name:<30} {filled:>6} {avg_rr:>5.1f}:1 {med_rr:>5.1f}:1 {signals:>7} {both_pct:>7.0f}%")
else:
    print("No groups meet criteria (avg R:R >= 1:1 with filled trades)")

# ── Signal completeness stats ─────────────────────────────────────────────────
print()
print("=== SIGNAL COMPLETENESS (how often SL+TP are parsed) ===")
print(f"{'Group':<30} {'Signals':>7} {'HasSL%':>7} {'HasTP%':>7} {'Both%':>7}")
print("-" * 60)
for name, g in sorted(ranked, key=lambda x: x[1]["has_both"] / max(x[1]["signals"], 1), reverse=True):
    if g["signals"] < 3:
        continue
    sl_pct = g["has_sl"] / g["signals"] * 100
    tp_pct = g["has_tp"] / g["signals"] * 100
    both_pct = g["has_both"] / g["signals"] * 100
    print(f"{name:<30} {g['signals']:>7} {sl_pct:>6.0f}% {tp_pct:>6.0f}% {both_pct:>6.0f}%")
