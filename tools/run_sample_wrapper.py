import traceback
from telegram_signal_copier.main import _run_sample, AppConfig
from telegram_signal_copier.models import TelegramSignalMessage

try:
    config = AppConfig.from_env()
    _run_sample(config, 'VIP Gold', 'wrap-1', 'BUY GOLD NOW @ 4700 SL 4690 TP1 4710', None)
except Exception:
    traceback.print_exc()
