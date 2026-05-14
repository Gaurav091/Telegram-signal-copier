from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services.signal_parser import SignalParser
from telegram_signal_copier.adapters.openai_client import OpenAIClient
from telegram_signal_copier.models import TelegramSignalMessage

cfg = AppConfig.from_env()
# instantiate parser without AI client to test heuristic behavior
parser = SignalParser(config=cfg, ai_client=None)

# sample text that previously produced 'ACTIVE' as symbol
text = "ALERT: SIGNAL ACTIVE NOW - BUY XAU AT 1800 SL 1790 TP 1810"
msg = TelegramSignalMessage(source_group="TestGroup", message_id="t-active-1", raw_text=text, image_path=None)

res = parser._heuristic_parse(msg, text)
print('Heuristic parse:')
print(res)

# sample text with only header word ACTIVE
text2 = "STATUS: ACTIVE - system heartbeat"
msg2 = TelegramSignalMessage(source_group="TestGroup", message_id="t-active-2", raw_text=text2, image_path=None)
res2 = parser._heuristic_parse(msg2, text2)
print('\nHeuristic parse (header only):')
print(res2)
