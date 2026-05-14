from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import ParsedSignal
from telegram_signal_copier.services.risk_engine import RiskEngine

cfg = AppConfig.from_env()
cfg.ensure_runtime_dirs()
engine = RiskEngine(cfg)

# Test with broker-suffixed symbol
sig = ParsedSignal(
    source_group="Test",
    message_id="t-m-1",
    symbol="XAUUSDm",
    side="BUY",
    entry_price=1800.0,
    stop_loss=1750.0,
    take_profits=[1820.0],
    confidence=0.95,
    raw_text="XAUUSDm BUY 1800 SL 1750 TP 1820",
)

decision = engine.evaluate(sig)
print("Symbol:", sig.symbol)
print("Decision:", decision.status)
print("Reasons:", decision.reasons)

# Test with base symbol
sig2 = ParsedSignal(
    source_group="Test",
    message_id="t-2",
    symbol="XAUUSD",
    side="BUY",
    entry_price=1800.0,
    stop_loss=1750.0,
    take_profits=[1820.0],
    confidence=0.95,
    raw_text="XAUUSD BUY 1800 SL 1750 TP 1820",
)
print('\n-- Base symbol test --')
print('Symbol:', sig2.symbol)
print('Decision:', engine.evaluate(sig2).status)
