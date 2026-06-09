"""3-week group performance analysis with R:R calculation."""
import MetaTrader5 as mt5
import datetime
from collections import defaultdict

if not mt5.initialize():
    print("MT5 init FAILED:", mt5.last_error())
    exit(1)

from_date = datetime.datetime.now() - datetime.timedelta(days=21)
to_date = datetime.datetime.now()
deals = mt5.history_deals_get(from_date, to_date)
mt5.shutdown()

SLUG_TO_NAME = {
    "FX-VIP-CLUB": "FX VIP CLUB",
    "GOLD-VIP-SIGNALS": "GOLD VIP SIGNALS",
    "ALGO-TRADING-FOR": "ALGO TRADING forex.",
    "XAUUSD-GOLD-SIGN": "XAUUSD GOLD SIGNAL",
    "CRYPTO-WITH-KEVI": "Crypto with kevin 3.0",
    "KRISHNA-CRYPTO-C": "Krishna crypto community",
    "FOREX-FOCUS": "FOREX FOCUS",
    "GOLD-EXPERTISE": "Gold Expertise",
    "ADAM-GOLD-MASTER": "Adam Gold Master",
    "STAR-TRADING-TM": "Star Trading",
    "DUBAI-TRADER-S-Z": "DUBAI TRADER'S ZONE",
    "NAS100-PRO-SIGN": "NAS100 PRO SIGNALS",
    "FOREX-TRADING-KI": "FOREX TRADING KING TIPS",
    "GTA-VIP-3-0": "GTA VIP 3.0",
    "GOLD-BIG-LOT-SIG": "GOLD BIG LOT SIGNALS",
    "PAUL-GOLD-TRADER": "PAUL GOLD TRADER",
    "GOLD-ANALYSIS-SI": "GOLD ANALYSIS SIGNALS",
    "TRADER-TACTICS": "Trader Tactics",
    "XAUUSD-VIP-PAID-": "XAUUSD VIP PAID SETUPS",
    "TRADE-WITH-JONSA": "TRADE WITH JONSAN",
    "INSIDER-TRADING": "INSIDER TRADING",
    "NEYMAR-GOLD-TRAD": "Neymar Gold Trader",
    "FOREX-MARKET-CON": "FOREX MARKET CONQUER",
    "MARKET-EDGE-PRO": "MARKET EDGE PRO",
    "TRADE-FOREX-WITH": "TRADE FOREX WITH",
    "SMOKE-TEST": "SMOKE-TEST",
}

# Map position_id -> channel + entry from opening deals
# SL/TP come from position info (deals don't carry sl/tp fields)
pos_ch = {}
pos_entry = {}
for d in deals:
    if d.entry == 0 and d.comment and d.comment.startswith("TG|"):
        parts = d.comment.split("|")
        if len(parts) >= 2:
            slug = parts[1]
            pos_ch[d.position_id] = SLUG_TO_NAME.get(slug, slug)
            pos_entry[d.position_id] = d.price

pbc = defaultdict(float)
wbc = defaultdict(int)
lbc = defaultdict(int)
tbc = defaultdict(int)
rr_data = defaultdict(list)

for d in deals:
    if d.entry != 1 or d.profit == 0:
        continue
    ch = pos_ch.get(d.position_id)
    if ch is None:
        continue
    pbc[ch] += d.profit
    tbc[ch] += 1
    if d.profit > 0:
        wbc[ch] += 1
    else:
        lbc[ch] += 1
    # Estimate R:R from deal profit and entry price
    # Typical risk: XAUUSD ~$10, BTCUSD ~$500, forex ~0.0010, indices ~50
    entry = pos_entry.get(d.position_id, 0)
    sym = d.symbol.upper()
    if "XAU" in sym or "GOLD" in sym:
        est_risk_usd = 10.0 * d.volume * 100  # $10 move * contract
    elif "BTC" in sym:
        est_risk_usd = 500.0 * d.volume
    elif "NAS" in sym or "US30" in sym or "SPX" in sym:
        est_risk_usd = 50.0 * d.volume * 10
    else:
        est_risk_usd = 0.0010 / max(entry, 0.0001) * d.volume * 100000 if entry > 0 else 10
    rr = abs(d.profit) / est_risk_usd if est_risk_usd > 0 else 0
    rr_data[ch].append({"profit": d.profit, "rr": rr})

ranked = sorted(pbc.items(), key=lambda x: x[1], reverse=True)

print(f"=== GROUP PERFORMANCE - Last 21 Days ===")
print(f"({from_date.strftime('%b %d')} - {to_date.strftime('%b %d, %Y')}  |  Account #272489632 Exness)")
print()
print(f"{'Rank':<5} {'Channel':<30} {'Profit':>8} {'Trades':>6} {'W':>3} {'L':>3} {'Win%':>5} {'AvgRR':>6} {'MinRR':>6}")
print("-" * 80)

for i, (name, profit) in enumerate(ranked, 1):
    t = tbc[name]
    w = wbc[name]
    l_val = lbc[name]
    win_pct = w / t * 100 if t > 0 else 0
    rrs = [r["rr"] for r in rr_data[name] if r["rr"] > 0]
    avg_rr = sum(rrs) / len(rrs) if rrs else 0
    min_rr = min(rrs) if rrs else 0
    marker = " <<<" if profit > 0 and avg_rr >= 1.0 and win_pct >= 50 else ""
    print(f"{i:<5} {name:<30} {profit:>8.2f} {t:>6} {w:>3} {l_val:>3} {win_pct:>4.0f}% {avg_rr:>5.1f}:1 {min_rr:>5.1f}:1{marker}")

print("-" * 80)
print(f"{'':<5} {'TOTAL':<30} {sum(pbc.values()):>8.2f} {sum(tbc.values()):>6}")

# Summary: groups meeting criteria
print()
print("=== GROUPS WITH PROFITABLE + MIN 1:1 R:R ===")
print(f"{'Channel':<30} {'Profit':>8} {'Win%':>5} {'AvgRR':>6} {'Trades':>6}")
print("-" * 60)
qualifying = [(n, p) for n, p in ranked if p > 0]
qualifying_rr = []
for name, profit in qualifying:
    rrs = [r["rr"] for r in rr_data[name] if r["rr"] > 0]
    avg_rr = sum(rrs) / len(rrs) if rrs else 0
    t = tbc[name]
    w = wbc[name]
    win_pct = w / t * 100 if t > 0 else 0
    if avg_rr >= 1.0:
        qualifying_rr.append((name, profit, win_pct, avg_rr, t))

if qualifying_rr:
    for name, profit, win_pct, avg_rr, t in sorted(qualifying_rr, key=lambda x: x[1], reverse=True):
        print(f"{name:<30} {profit:>8.2f} {win_pct:>4.0f}% {avg_rr:>5.1f}:1 {t:>6}")
else:
    print("No groups meet all criteria (profitable + avg R:R >= 1:1)")
