import importlib, traceback

try:
    m = importlib.import_module('tools.mt5_log_watcher')
    m.main()
except Exception:
    traceback.print_exc()
