import importlib, traceback

try:
    m = importlib.import_module('tools.bridge_autofix_daemon')
    m.main(6)
except Exception:
    traceback.print_exc()
