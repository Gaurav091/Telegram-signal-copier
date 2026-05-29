import traceback
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.main import build_pipeline
from telegram_signal_copier.models import TelegramSignalMessage

def main():
    try:
        config = AppConfig.from_env()
        pipeline = build_pipeline(config)
        msg = TelegramSignalMessage(source_group='VIP Gold', message_id='direct-1', raw_text='BUY GOLD NOW @ 4700 SL 4690 TP1 4710')
        outcome = pipeline.process_message(msg)
        print(outcome.to_dict())
    except Exception as exc:
        traceback.print_exc()

if __name__ == '__main__':
    main()
