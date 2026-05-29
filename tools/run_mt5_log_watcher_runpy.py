import runpy, traceback

try:
    runpy.run_path('tools/mt5_log_watcher.py', run_name='__main__')
except Exception:
    traceback.print_exc()
