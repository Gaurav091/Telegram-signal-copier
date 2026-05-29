from pathlib import Path
import sys
sys.path.insert(0, str(Path('src').resolve()))
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services.signal_parser import SignalParser
from telegram_signal_copier.models.contracts import TelegramSignalMessage
import dataclasses, json

cfg = AppConfig.from_env(project_root=Path('.').resolve())
parser = SignalParser(cfg, None)
text = '''XAUUSD SELL NOW:  4582 4586

TAKE PROFIT:      4580
TAKE PROFIT:     4575  ✅
TAKE PROFIT:      4556

STOP LOSS:         4600

FIRST EDUCATED THEN TRADE
'''
msg = TelegramSignalMessage(source_group='TEST', message_id='1', raw_text=text)
res = parser.parse(msg)
print(json.dumps(dataclasses.asdict(res.signal), indent=2, default=str))
print('used_ai=', res.used_ai)
