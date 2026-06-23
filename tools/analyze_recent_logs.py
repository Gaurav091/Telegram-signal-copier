"""Analyze the last N days of pipeline logs to understand signal processing patterns."""
import json
import os
import sys
from collections import Counter
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

def analyze_logs(days=None, last_n_lines=None):
    files = sorted(
        f for f in os.listdir(LOGS_DIR)
        if f.startswith("pipeline_2026-06") and f.endswith(".jsonl")
    )
    
    all_entries = []
    for fname in files:
        fpath = LOGS_DIR / fname
        lines = fpath.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                all_entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    
    if last_n_lines:
        all_entries = all_entries[-last_n_lines:]
    
    print(f"=== Pipeline Log Analysis (last {len(all_entries)} entries) ===\n")
    
    # Action breakdown
    actions = Counter(e.get("action_taken", "NONE") for e in all_entries)
    print("--- Actions ---")
    for action, count in actions.most_common():
        print(f"  {action}: {count} ({100*count/len(all_entries):.1f}%)")
    
    # Intent breakdown
    intents = Counter(e.get("intent", "NONE") for e in all_entries)
    print("\n--- Intents ---")
    for intent, count in intents.most_common():
        print(f"  {intent}: {count} ({100*count/len(all_entries):.1f}%)")
    
    # Top rejection reasons
    rejection_reasons = Counter()
    for e in all_entries:
        for r in e.get("rejection_reasons", []):
            rejection_reasons[r] += 1
    print("\n--- Top Rejection Reasons ---")
    for reason, count in rejection_reasons.most_common(15):
        print(f"  {reason}: {count}")
    
    # Execution status breakdown
    exec_statuses = Counter(e.get("execution_status") or "N/A" for e in all_entries)
    print("\n--- Execution Statuses ---")
    for status, count in exec_statuses.most_common():
        print(f"  {status}: {count}")
    
    # Source groups
    sources = Counter(e.get("source_group", "?") for e in all_entries)
    print("\n--- Top Source Groups ---")
    for source, count in sources.most_common(10):
        print(f"  {source}: {count}")
    
    # Show APPROVED signals
    approved = [e for e in all_entries if e.get("action_taken") == "APPROVED"]
    print(f"\n--- APPROVED Signals ({len(approved)}) ---")
    for e in approved[:20]:
        ext = e.get("extraction", {})
        print(f"  {e.get('source_group','?')} | {ext.get('symbol','?')} {ext.get('side','?')} @ {ext.get('entry_price','?')} SL={ext.get('stop_loss','?')} TP={ext.get('take_profits','?')} conf={ext.get('confidence','?')}")
    
    # Show SKIPPED signals (informational/update)
    skipped = [e for e in all_entries if e.get("action_taken") == "SKIPPED"]
    print(f"\n--- SKIPPED Signals ({len(skipped)}) ---")
    for e in skipped[:10]:
        print(f"  {e.get('source_group','?')} | intent={e.get('intent','?')} text={e.get('text_snippet','')[:80]}")
    
    # Show signals that were rejected but look like they could be valid
    rejected = [e for e in all_entries if e.get("action_taken") == "REJECTED"]
    print(f"\n--- REJECTED Signals ({len(rejected)}) ---")
    reasons_to_skip = {"Missing side", "Missing symbol"}
    for e in rejected[:30]:
        ext = e.get("extraction", {})
        reasons = e.get("rejection_reasons", [])
        print(f"  {e.get('source_group','?')} | {ext.get('symbol','?')} {ext.get('side','?')} conf={ext.get('confidence','?')} reasons={reasons}")
    
    # Confidence distribution for all signals
    confidences = [e.get("extraction", {}).get("confidence", 0) for e in all_entries if e.get("extraction")]
    if confidences:
        print(f"\n--- Confidence Distribution ---")
        buckets = Counter()
        for c in confidences:
            if c < 0.3:
                buckets["<0.3"] += 1
            elif c < 0.5:
                buckets["0.3-0.5"] += 1
            elif c < 0.7:
                buckets["0.5-0.7"] += 1
            elif c < 0.9:
                buckets["0.7-0.9"] += 1
            else:
                buckets["0.9+"] += 1
        for bucket, count in sorted(buckets.items()):
            print(f"  {bucket}: {count}")
    
    # Show entries with non-null execution_status
    executed = [e for e in all_entries if e.get("execution_status")]
    print(f"\n--- Executed Entries ({len(executed)}) ---")
    for e in executed[:20]:
        ext = e.get("extraction", {})
        print(f"  {e.get('source_group','?')} | {ext.get('symbol','?')} {ext.get('side','?')} | status={e.get('execution_status')} ticket={e.get('order_ticket')} error={e.get('execution_error','')[:60]}")

if __name__ == "__main__":
    last_n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    analyze_logs(last_n_lines=last_n)