"""Domain constants for the Telegram Signal Copier.

All symbol-level tables live here so they can be imported by any module
without creating circular dependencies.  Public names (no leading underscore)
are intentional — these are module-level constants, not private state.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Symbol alias table  (common shorthand → canonical MT5 symbol name)
# ---------------------------------------------------------------------------
SYMBOL_ALIASES: dict[str, str] = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAG": "XAGUSD",
    "DOW": "US30",
    "DJ30": "US30",
    "DOWJONES": "US30",
    "US500": "SPX500",
    "SP500": "SPX500",
    "SPX": "SPX500",
    "NASDAQ": "NAS100",
    "NDX": "NAS100",
    "NQ": "NAS100",
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
}

# ---------------------------------------------------------------------------
# Realistic price ranges per symbol (blocks obvious OCR/AI mis-parses)
# ---------------------------------------------------------------------------
SYMBOL_PRICE_RANGES: dict[str, tuple[float, float]] = {
    "XAUUSD": (3000.0, 8000.0),
    "XAGUSD": (15.0, 150.0),
    "EURUSD": (0.80, 1.60),
    "GBPUSD": (1.00, 2.00),
    "USDJPY": (80.0, 200.0),
    "BTCUSD": (5000.0, 250000.0),
    "ETHUSD": (100.0, 25000.0),
    "USOIL": (20.0, 200.0),
    "US30": (20000.0, 60000.0),
    "NAS100": (8000.0, 30000.0),
    "SPX500": (2000.0, 8000.0),
}

# ---------------------------------------------------------------------------
# Minimum broker-safe distance between entry and protective levels
# ---------------------------------------------------------------------------
SYMBOL_MIN_STOP: dict[str, float] = {
    "XAUUSD": 10.0,
    "XAGUSD": 0.20,
    "BTCUSD": 50.0,
    "ETHUSD": 5.0,
    "NAS100": 5.0,
    "US30": 10.0,
    "SPX500": 2.0,
}

# Minimum distance between entry and TP1
SYMBOL_MIN_TP1_DISTANCE: dict[str, float] = {
    "XAUUSD": 3.0,
}

# ---------------------------------------------------------------------------
# Minimum plausible entry prices for crypto symbols
# (guards against OCR dropping leading digits, e.g. 77645.45 → 645.45)
# ---------------------------------------------------------------------------
CRYPTO_ENTRY_MIN: dict[str, float] = {
    "BTCUSD": 5000.0,
    "ETHUSD": 100.0,
}
