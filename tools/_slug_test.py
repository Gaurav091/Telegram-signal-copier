import sys; sys.path.insert(0,'src')
from telegram_signal_copier.models.contracts import _comment_source_slug

groups = [
    'GOLD VIP SIGNALS',
    'ALGO TRADING forex.',
    'XAUUSD GOLD SIGNAL',
    'Crypto with kevin 3.0',
    'Krishna crypto community',
    'FOREX FOCUS',
    'Gold Expertise',
    'Adam Gold Master',
    'Star Trading',
    "DUBAI TRADER'S ZONE",
    'NAS100 PRO SIGNALS',
    'FX VIP CLUB',
    '@fxvipclub',
    '1935701558',
    '2219598931',
]
for g in groups:
    slug = _comment_source_slug(g)[:16]
    print(f'{g!r:40s} => TG|{slug}|MSGID')
