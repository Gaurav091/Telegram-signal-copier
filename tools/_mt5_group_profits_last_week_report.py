import MetaTrader5 as mt5
import datetime
from collections import defaultdict

"""
Last-week group performance report (ranks + keep/remove recommendations).

How it works (consistent with other repo scripts):
- Identify each closed deal's "channel" by mapping position_id to channel name:
  TG opening deals have comment starting with "TG|" and entry == 0.
  We store position_id -> channel.
- Aggregate profits from closing deals:
  We sum d.profit for deals where entry == 1 and profit != 0,
  grouped by that channel.
- Rank channels by total profit (desc).
"""

# ===== Time window (last 7 full days) =====
to_date = datetime.datetime.now()
from_date = to_date - datetime.timedelta(days=7)
deals = None

# ===== MT5 init =====
if not mt5.initialize():
    print("MT5 init FAILED:", mt5.last_error())
    raise SystemExit(1)

deals = mt5.history_deals_get(from_date, to_date) or []
mt5.shutdown()

# ===== Map slug -> display name =====
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

# Map position_id -> channel name from TG| opening deals (entry=0)
pos_to_channel = {}
pos_to_entry_price = {}  # for RR approximation

for d in deals:
    # Opening deals: entry==0 and comment starts with TG|
    if getattr(d, "entry", None) != 0:
        continue
    comment = getattr(d, "comment", "") or ""
    if not comment.startswith("TG|"):
        continue
    parts = comment.split("|")
    if len(parts) < 2:
        continue
    slug = parts[1]
    pos_to_channel[getattr(d, "position_id", "")] = SLUG_TO_NAME.get(slug, slug)
    pos_to_entry_price[getattr(d, "position_id", "")] = getattr(d, "price", 0) or 0

# Aggregate metrics by channel
profit_by_channel = defaultdict(float)
wins_by_channel = defaultdict(int)
losses_by_channel = defaultdict(int)
trades_by_channel = defaultdict(int)

# RR estimate buckets (same heuristic style as _mt5_group_profits_3w.py)
rr_data = defaultdict(list)

for d in deals:
    # Closing deals: entry==1, profit != 0
    if getattr(d, "entry", None) != 1:
        continue
    profit = getattr(d, "profit", 0) or 0
    if profit == 0:
        continue

    position_id = getattr(d, "position_id", "")
    channel = pos_to_channel.get(position_id)
    if channel is None:
        continue

    profit_by_channel[channel] += profit
    trades_by_channel[channel] += 1
    if profit > 0:
        wins_by_channel[channel] += 1
    else:
        losses_by_channel[channel] += 1

    # RR estimate (best-effort; relies on contract-size heuristic like existing scripts)
    entry = pos_to_entry_price.get(position_id, 0) or 0
    sym = (getattr(d, "symbol", "") or "").upper()

    # Typical risk approximations used by the repo script:
    if "XAU" in sym or "GOLD" in sym:
        est_risk_usd = 10.0 * getattr(d, "volume", 0) * 100
    elif "BTC" in sym:
        est_risk_usd = 500.0 * getattr(d, "volume", 0)
    elif "NAS" in sym or "US30" in sym or "SPX" in sym:
        est_risk_usd = 50.0 * getattr(d, "volume", 0) * 10
    else:
        # generic forex-like estimate: profit scale vs entry price
        # (fallback) - keep consistent with other script behavior
        est_risk_usd = (0.0010 / max(entry, 0.0001)) * getattr(d, "volume", 0) * 100000 if entry > 0 else 10

    rr = abs(profit) / est_risk_usd if est_risk_usd > 0 else 0
    rr_data[channel].append({"profit": profit, "rr": rr})

# Ranking
ranked = sorted(profit_by_channel.items(), key=lambda x: x[1], reverse=True)

# Print report
print(f"=== GROUP PERFORMANCE - Last 7 Days ===")
print(f"({from_date.strftime('%b %d')} - {to_date.strftime('%b %d, %Y')}  |  MT5 deals history)")
print()

print(f"{'Rank':<5} {'Channel':<32} {'Profit':>10} {'Trades':>7} {'W':>4} {'L':>4} {'Win%':>6} {'AvgRR':>8} {'MinRR':>8}")
print("-" * 90)

rows = []
for i, (name, total_profit) in enumerate(ranked, 1):
    t = trades_by_channel[name]
    w = wins_by_channel[name]
    l = losses_by_channel[name]
    win_pct = (w / t * 100) if t else 0

    rrs = [x["rr"] for x in rr_data[name] if x.get("rr", 0) > 0]
    avg_rr = (sum(rrs) / len(rrs)) if rrs else 0
    min_rr = min(rrs) if rrs else 0

    rows.append(
        {
            "rank": i,
            "channel": name,
            "profit": total_profit,
            "trades": t,
            "wins": w,
            "losses": l,
            "win_pct": win_pct,
            "avg_rr": avg_rr,
            "min_rr": min_rr,
        }
    )

    print(
        f"{i:<5} {name:<32} {total_profit:>10.2f} {t:>7} {w:>4} {l:>4} {win_pct:>6.0f}% {avg_rr:>8.1f} {min_rr:>8.1f}"
    )

total_profit_all = sum(profit_by_channel.values())
total_trades_all = sum(trades_by_channel.values())
print("-" * 90)
print(f"{'':5} {'TOTAL':<32} {total_profit_all:>10.2f} {total_trades_all:>7}")

# Keep/Remove recommendations
# Heuristic rules:
# - keep if profit > 0 AND win% >= 50 AND avgRR >= 1.0 (best-effort)
# - remove if profit < 0 (or very poor win% with negative profit)
keep_rows = []
remove_rows = []
neutral_rows = []

for r in rows:
    profitable = r["profit"] > 0
    ok_rr = r["avg_rr"] >= 1.0
    ok_win = r["win_pct"] >= 50
    if profitable and ok_rr and ok_win:
        keep_rows.append(r)
    elif r["profit"] < 0 and r["win_pct"] < 50:
        remove_rows.append(r)
    else:
        neutral_rows.append(r)

print()
print("=== KEEP / REMOVE (heuristic recommendation) ===")
if keep_rows:
    print("KEEP (profitable + win%>=50 + avgRR>=1:1):")
    for r in sorted(keep_rows, key=lambda x: x["profit"], reverse=True):
        print(f"  - Rank {r['rank']}: {r['channel']} | Profit {r['profit']:.2f} | Win% {r['win_pct']:.0f}% | AvgRR {r['avg_rr']:.1f}:1 | Trades {r['trades']}")
else:
    print("KEEP: no groups matched criteria.")

print()

if remove_rows:
    print("REMOVE (negative profit + win%<50):")
    for r in sorted(remove_rows, key=lambda x: x["profit"]):
        print(f"  - Rank {r['rank']}: {r['channel']} | Profit {r['profit']:.2f} | Win% {r['win_pct']:.0f}% | AvgRR {r['avg_rr']:.1f}:1 | Trades {r['trades']}")
else:
    print("REMOVE: no groups matched criteria.")

print()
if neutral_rows:
    print("NEUTRAL (not enough edge by criteria; review manually):")
    for r in sorted(neutral_rows, key=lambda x: x["rank"]):
        print(f"  - Rank {r['rank']}: {r['channel']} | Profit {r['profit']:.2f} | Win% {r['win_pct']:.0f}% | AvgRR {r['avg_rr']:.1f}:1 | Trades {r['trades']}")
