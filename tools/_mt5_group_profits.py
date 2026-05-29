import MetaTrader5 as mt5
import datetime
from collections import defaultdict

if not mt5.initialize():
    print("MT5 init FAILED:", mt5.last_error())
    exit(1)

from_date = datetime.datetime.now() - datetime.timedelta(days=10)
to_date   = datetime.datetime.now()

deals = mt5.history_deals_get(from_date, to_date)
mt5.shutdown()

SLUG_TO_NAME = {
    "FX-VIP-CLUB":         "FX VIP CLUB",
    "GOLD-VIP-SIGNALS":    "GOLD VIP SIGNALS",
    "ALGO-TRADING-FOR":    "ALGO TRADING forex.",
    "XAUUSD-GOLD-SIGN":    "XAUUSD GOLD SIGNAL",
    "CRYPTO-WITH-KEVI":    "Crypto with kevin 3.0",
    "KRISHNA-CRYPTO-C":    "Krishna crypto community",
    "FOREX-FOCUS":         "FOREX FOCUS",
    "GOLD-EXPERTISE":      "Gold Expertise",
    "ADAM-GOLD-MASTER":    "Adam Gold Master",
    "STAR-TRADING-TM":     "Star Trading",
    "DUBAI-TRADER-S-Z":    "DUBAI TRADER'S ZONE",
    "NAS100-PRO-SIGN":     "NAS100 PRO SIGNALS",
    "FOREX-TRADING-KI":    "FOREX TRADING KING TIPS",
    "GTA-VIP-3-0":         "GTA VIP 3.0",
    "GOLD-BIG-LOT-SIG":    "GOLD BIG LOT SIGNALS",
    "PAUL-GOLD-TRADER":    "PAUL GOLD TRADER",
    "GOLD-ANALYSIS-SI":    "GOLD ANALYSIS SIGNALS",
    "TRADER-TACTICS":      "Trader Tactics",
    "XAUUSD-VIP-PAID-":    "XAUUSD VIP PAID SETUPS",
    "TRADE-WITH-JONSA":    "TRADE WITH JONSAN",
    "INSIDER-TRADING":     "INSIDER TRADING",
    "NEYMAR-GOLD-TRAD":    "Neymar Gold Trader",
    "FOREX-MARKET-CON":    "FOREX MARKET CONQUER",
}

# Map position_id -> channel name from TG| opening deals (entry=0)
pos_to_channel = {}
for d in deals:
    if d.entry == 0 and d.comment and d.comment.startswith("TG|"):
        parts = d.comment.split("|")
        if len(parts) >= 2:
            slug = parts[1]
            pos_to_channel[d.position_id] = SLUG_TO_NAME.get(slug, slug)

profit_by_channel = defaultdict(float)
wins_by_channel   = defaultdict(int)
losses_by_channel = defaultdict(int)
trades_by_channel = defaultdict(int)

# Accumulate P&L from closing deals (entry=1) matched to their channel
for d in deals:
    if d.entry != 1:
        continue
    if d.profit == 0:
        continue
    channel = pos_to_channel.get(d.position_id)
    if channel is None:
        continue
    profit_by_channel[channel] += d.profit
    trades_by_channel[channel] += 1
    if d.profit > 0:
        wins_by_channel[channel] += 1
    else:
        losses_by_channel[channel] += 1

ranked = sorted(profit_by_channel.items(), key=lambda x: x[1], reverse=True)

print("=== GROUP PERFORMANCE - Last 10 Days ===")
print("(May 17-27, 2026  |  Account #272489632 Exness)")
print()
print(f"{'Rank':<5} {'Channel':<32} {'Profit (USD)':>12} {'Trades':>7} {'W':>4} {'L':>4} {'Win%':>6}")
print("-" * 74)
for i, (name, profit) in enumerate(ranked, 1):
    t = trades_by_channel[name]
    w = wins_by_channel[name]
    l = losses_by_channel[name]
    wpct = (w / t * 100) if t else 0
    marker = " <<< BEST" if i == 1 else ""
    print(f"{i:<5} {name:<32} {profit:>12.2f} {t:>7} {w:>4} {l:>4} {wpct:>5.0f}%{marker}")

total = sum(profit_by_channel.values())
print("-" * 74)
print(f"{'':5} {'TOTAL':<32} {total:>12.2f}")
