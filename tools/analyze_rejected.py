"""Analyze rejected messages to find parseable patterns."""
import json
import os
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

def analyze():
    all_entries = []
    for fname in sorted(os.listdir(LOGS_DIR)):
        if fname.startswith("pipeline_2026-06") and fname.endswith(".jsonl"):
            for line in (LOGS_DIR / fname).read_text(encoding="utf-8").splitlines():
                try:
                    all_entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    rejected = [e for e in all_entries if e.get("action_taken") == "REJECTED"]

    # Group by source and rejection reason
    print(f"=== REJECTED SIGNALS ANALYSIS ({len(rejected)} total) ===\n")

    # Show signals that have symbol + side but missing SL/TP (most promising to fix)
    has_both = [e for e in rejected if
                e.get("extraction", {}).get("symbol") and
                e.get("extraction", {}).get("side") and
                not e.get("extraction", {}).get("stop_loss")]
    print(f"\n--- Has symbol+side but MISSING SL ({len(has_both)}) ---")
    for e in has_both[:20]:
        ext = e.get("extraction", {})
        print(f"  {e.get('source_group','?')[:30]:30} | {ext.get('symbol','?'):10} {ext.get('side','?'):5} entry={ext.get('entry_price','?')} | reasons={e.get('rejection_reasons',[])} | text={e.get('text_snippet','')[:100]}")

    # Show signals that have symbol+side+SL but missing TP
    has_sl_no_tp = [e for e in rejected if
                    e.get("extraction", {}).get("symbol") and
                    e.get("extraction", {}).get("side") and
                    e.get("extraction", {}).get("stop_loss") and
                    not e.get("extraction", {}).get("take_profits")]
    print(f"\n--- Has symbol+side+SL but MISSING TP ({len(has_sl_no_tp)}) ---")
    for e in has_sl_no_tp[:20]:
        ext = e.get("extraction", {})
        print(f"  {e.get('source_group','?')[:30]:30} | {ext.get('symbol','?'):10} {ext.get('side','?'):5} entry={ext.get('entry_price','?')} SL={ext.get('stop_loss','?')} | text={e.get('text_snippet','')[:100]}")

    # Show signals with wrong symbol (numbers parsed as symbols)
    wrong_sym = [e for e in rejected if
                 e.get("extraction", {}).get("symbol") and
                 any("not allowed" in r for r in e.get("rejection_reasons", []))]
    print(f"\n--- Symbol not allowed ({len(wrong_sym)}) ---")
    for e in wrong_sym[:20]:
        ext = e.get("extraction", {})
        print(f"  {e.get('source_group','?')[:30]:30} | sym={ext.get('symbol','?'):15} {ext.get('side','?'):5} | reasons={[r for r in e.get('rejection_reasons',[]) if 'symbol' in r.lower()]} | text={e.get('text_snippet','')[:100]}")

    # Show signals that are purely informational (no symbol, no side)
    no_data = [e for e in rejected if
               not e.get("extraction", {}).get("symbol") and
               not e.get("extraction", {}).get("side")]
    print(f"\n--- No symbol or side (informational) ({len(no_data)}) ---")
    for e in no_data[:15]:
        print(f"  {e.get('source_group','?')[:30]:30} | text={e.get('text_snippet','')[:100]}")

    # Show confidence-rejected signals
    low_conf = [e for e in rejected if
                any("Confidence" in r for r in e.get("rejection_reasons", []))]
    print(f"\n--- Confidence too low ({len(low_conf)}) ---")
    for e in low_conf[:15]:
        ext = e.get("extraction", {})
        print(f"  {e.get('source_group','?')[:30]:30} | conf={ext.get('confidence',0):.2f} sym={ext.get('symbol','?')} side={ext.get('side','?')} | text={e.get('text_snippet','')[:100]}")

    # Show SL direction/distance rejections
    sl_issues = [e for e in rejected if
                 any("SL" in r and ("below" in r.lower() or "above" in r.lower() or "distance" in r.lower() or "close" in r.lower()) for r in e.get("rejection_reasons", []))]
    print(f"\n--- SL direction/distance issues ({len(sl_issues)}) ---")
    for e in sl_issues[:15]:
        ext = e.get("extraction", {})
        print(f"  {e.get('source_group','?')[:30]:30} | {ext.get('symbol','?'):10} {ext.get('side','?'):5} entry={ext.get('entry_price','?')} SL={ext.get('stop_loss','?')} TP={ext.get('take_profits','?')} | reasons={e.get('rejection_reasons',[])}")

if __name__ == "__main__":
    analyze()