from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.main import build_pipeline
from telegram_signal_copier.models import TelegramSignalMessage

c = AppConfig.from_env()
print('AI_MAX_REQUESTS_PER_MINUTE=', c.ai_max_requests_per_minute, flush=True)
print('AI_CACHE_TTL_SECONDS=', c.ai_cache_ttl_seconds, flush=True)

pipeline = build_pipeline(c)
texts = [
    'NEW BUY EURUSD ENTRY 1.100 SL 1.095 TP 1.105',
    'NEW SELL GBPUSD ENTRY 1.300 SL 1.310 TP 1.290',
    'EURUSD BUY 1.101 SL 1.096 TP 1.110',
    'NEW BUY XAUUSD ENTRY 1950 SL 1935 TP 1975',
    'ALERT BUY US30 ENTRY 34150 SL 34000 TP 34500',
    'SELL USDJPY 135.50 SL 136.00 TP 134.00',
    'LONG NAS100 ENTRY 16600 SL 16400 TP 16900',
    'Short GOLD ENTRY 1948 SL 1960 TP 1925'
]
used_ai_count = 0
for i, txt in enumerate(texts, start=1):
    msg = TelegramSignalMessage(source_group='batch', message_id=f'text-{i}', raw_text=txt, image_path=None)
    out = pipeline.process_message(msg)
    print(i, out.parse_result.used_ai, out.parse_result.signal.symbol, out.decision.status, flush=True)
    if out.parse_result.used_ai:
        used_ai_count += 1

# Two image-based messages (duplicate) to test caching behavior
img = 'runtime/media/11619.jpg'
for i in range(1,3):
    msg = TelegramSignalMessage(source_group='batch', message_id=f'img-{i}', raw_text='', image_path=img)
    out = pipeline.process_message(msg)
    print('IMG', i, out.parse_result.used_ai, out.parse_result.signal.symbol, out.decision.status, flush=True)
    if out.parse_result.used_ai:
        used_ai_count += 1

print('Total AI calls used in this run (approx):', used_ai_count, flush=True)
