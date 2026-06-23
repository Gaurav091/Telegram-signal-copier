"""Deep analysis: focus on real signals that were rejected."""
import json
import glob
from collections import Counter


def main():
    files = sorted(glob.glob("logs/pipeline_*.jsonl"), reverse=True)
    signals = []
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
            for line in reversed(lines):
                if len(signals) >= 300:
                    break
                try:
                    entry = json.loads(line.strip())
                    signals.append(entry)
                except Exception:
                    pass
        if len(signals) >= 300:
            break

    signals = signals[:300]

    # Separate FILLED vs REJECTED
    filled = []
    rejected = []
    for s in signals:
        action = s.get("action_taken", "UNKNOWN")
        if action == "FILLED":
            filled.append(s)
        elif action == "REJECTED":
            rejected.append(s)

    print(f"=== FILLED SIGNALS ({len(filled)}) ===")
    for s in filled:
        ext = s.get("extraction") or {}
        print(f"  symbol={ext.get('symbol')} side={ext.get('side')} entry={ext.get('entry_price')} "
              f"sl={ext.get('stop_loss')} tp={ext.get('take_profits')} conf={ext.get('confidence', 0):.2f} "
              f"parser={ext.get('parser_name')} intent={s.get('intent')}")
        text = s.get("text_snippet", "")
        print(f"    text: {text[:150]}")
        print()

    # Now analyze rejected signals with cluster context (likely real signals)
    print(f"\n=== REJECTED SIGNALS WITH CLUSTER CONTEXT ({sum(1 for s in rejected if 'CLUSTER CONTEXT' in (s.get('text_snippet') or ''))}) ===")
    for s in rejected:
        text = s.get("text_snippet", "")
        if "CLUSTER CONTEXT" not in text:
            continue
        ext = s.get("extraction") or {}
        print(f"  symbol={ext.get('symbol')} side={ext.get('side')} entry={ext.get('entry_price')} "
              f"sl={ext.get('stop_loss')} tp={ext.get('take_profits')} conf={ext.get('confidence', 0):.2f} "
              f"parser={ext.get('parser_name')} intent={s.get('intent')}")
        print(f"    rejection: {s.get('rejection_reasons')}")
        print(f"    text: {text[:200]}")
        print()

    # Look for rejected signals that look like actual trades (have numbers resembling prices)
    print(f"\n=== REJECTED SIGNALS WITH POTENTIAL TRADE DATA ===")
    import re
    for s in rejected:
        text = s.get("text_snippet", "")
        ext = s.get("extraction") or {}
        # Look for text that has BUY/SELL and numbers (potential signals)
        has_direction = bool(re.search(r'\b(BUY|SELL|LONG|SHORT)\b', text.upper()))
        has_prices = bool(re.search(r'\b\d{4,5}\b', text))
        has_tp_sl = bool(re.search(r'\b(TP|SL|TARGET|STOP)\b', text.upper()))
        
        if has_direction and (has_prices or has_tp_sl) and not ext.get("symbol"):
            print(f"  intent={s.get('intent')} action={s.get('action_taken')}")
            print(f"    rejection: {s.get('rejection_reasons')}")
            print(f"    text: {text[:200]}")
            print()

    # Check rejected signals with garbage symbols
    print(f"\n=== REJECTED SIGNALS WITH GARBAGE SYMBOLS ===")
    garbage_symbols = {"2026", "919887628647", "4209", "D0E91022", "4156", "64750", "DJPSMWF1Y3", "1100", "60280", "4201", "4190", "4183"}
    for s in rejected:
        ext = s.get("extraction") or {}
        sym = ext.get("symbol", "")
        if sym in garbage_symbols:
            print(f"  symbol={sym} side={ext.get('side')} entry={ext.get('entry_price')}")
            print(f"    rejection: {s.get('rejection_reasons')}")
            print(f"    text: {s.get('text_snippet', '')[:200]}")
            print()


if __name__ == "__main__":
    main()