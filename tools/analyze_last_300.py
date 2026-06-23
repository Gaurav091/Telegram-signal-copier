"""Analyze the last 300 pipeline signals for parsing issues."""
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
    print(f"Total signals loaded: {len(signals)}")

    actions = Counter()
    intents = Counter()
    symbols = Counter()
    sides = Counter()
    parsers = Counter()
    has_entry = 0
    has_sl = 0
    has_tp = 0
    has_symbol = 0
    has_side = 0
    low_confidence = 0
    no_symbol = []
    no_side = []
    no_entry = []
    rejection_reasons = Counter()
    parse_failures = []

    for s in signals:
        action = s.get("action_taken", "UNKNOWN")
        actions[action] += 1
        intent = s.get("intent", "UNKNOWN")
        intents[intent] += 1

        extraction = s.get("extraction") or {}
        symbol = extraction.get("symbol")
        side = extraction.get("side")
        entry = extraction.get("entry_price")
        sl = extraction.get("stop_loss")
        tps = extraction.get("take_profits") or []
        conf = extraction.get("confidence", 0)
        parser = extraction.get("parser_name", "unknown")
        raw_text = s.get("text_snippet", "")

        parsers[parser] += 1

        if symbol:
            has_symbol += 1
            symbols[symbol] += 1
        else:
            no_symbol.append({"text": raw_text[:120], "action": action, "intent": intent, "parser": parser})

        if side:
            has_side += 1
            sides[side] += 1
        else:
            no_side.append({"text": raw_text[:120], "action": action, "intent": intent})

        if entry is not None:
            has_entry += 1
        else:
            no_entry.append({"text": raw_text[:120], "action": action, "symbol": symbol, "side": side, "parser": parser})

        if sl is not None:
            has_sl += 1

        if tps:
            has_tp += 1

        if conf < 0.3:
            low_confidence += 1
            parse_failures.append({
                "text": raw_text[:120],
                "symbol": symbol,
                "side": side,
                "entry": entry,
                "sl": sl,
                "tps": tps,
                "conf": conf,
                "action": action,
                "parser": parser,
            })

        for r in (s.get("rejection_reasons") or []):
            rejection_reasons[r] += 1

    print()
    print("=== ACTION DISTRIBUTION ===")
    for k, v in actions.most_common():
        print(f"  {k}: {v}")

    print()
    print("=== INTENT DISTRIBUTION ===")
    for k, v in intents.most_common():
        print(f"  {k}: {v}")

    print()
    print("=== PARSER DISTRIBUTION ===")
    for k, v in parsers.most_common():
        print(f"  {k}: {v}")

    print()
    print("=== FIELD EXTRACTION RATES ===")
    n = len(signals)
    print(f"  Symbol: {has_symbol}/{n} ({100*has_symbol/n:.1f}%)")
    print(f"  Side:   {has_side}/{n} ({100*has_side/n:.1f}%)")
    print(f"  Entry:  {has_entry}/{n} ({100*has_entry/n:.1f}%)")
    print(f"  SL:     {has_sl}/{n} ({100*has_sl/n:.1f}%)")
    print(f"  TP:     {has_tp}/{n} ({100*has_tp/n:.1f}%)")
    print(f"  Low confidence (<0.3): {low_confidence}/{n}")

    print()
    print("=== TOP SYMBOLS ===")
    for k, v in symbols.most_common(15):
        print(f"  {k}: {v}")

    print()
    print("=== SIDES ===")
    for k, v in sides.most_common():
        print(f"  {k}: {v}")

    print()
    print("=== REJECTION REASONS (top 15) ===")
    for k, v in rejection_reasons.most_common(15):
        print(f"  {k}: {v}")

    print()
    print(f"=== NO SYMBOL DETECTED (showing first 30 of {len(no_symbol)}) ===")
    for ns in no_symbol[:30]:
        print(f"  action={ns['action']} intent={ns['intent']} parser={ns['parser']}")
        print(f"    text: {ns['text']}")
        print()

    print()
    print(f"=== NO SIDE DETECTED (showing first 20 of {len(no_side)}) ===")
    for ns in no_side[:20]:
        print(f"  action={ns['action']} intent={ns['intent']}")
        print(f"    text: {ns['text']}")
        print()

    print()
    print(f"=== NO ENTRY DETECTED (showing first 20 of {len(no_entry)}) ===")
    for ne in no_entry[:20]:
        print(f"  action={ne['action']} symbol={ne['symbol']} side={ne['side']} parser={ne['parser']}")
        print(f"    text: {ne['text']}")
        print()

    print()
    print(f"=== LOW CONFIDENCE SIGNALS (showing first 30 of {len(parse_failures)}) ===")
    for pf in parse_failures[:30]:
        print(f"  conf={pf['conf']:.2f} action={pf['action']} parser={pf['parser']}")
        print(f"    text: {pf['text']}")
        print(f"    symbol={pf['symbol']} side={pf['side']} entry={pf['entry']} sl={pf['sl']} tp={pf['tps']}")
        print()


if __name__ == "__main__":
    main()