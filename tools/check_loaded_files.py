import telegram_signal_copier.main as m
print(m.__file__)
import telegram_signal_copier.adapters.telegram_client as tc
print(tc.__file__)
# Check _run_with_restarts source to confirm BaseException patch is live
import inspect
src = inspect.getsource(m._run_with_restarts)
print('BaseException in source:', 'BaseException' in src)
print('_event_to_message in tc:', hasattr(tc.TelegramSignalListener, '_event_to_message'))
