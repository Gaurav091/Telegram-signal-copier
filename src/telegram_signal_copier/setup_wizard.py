"""Backward-compatible facade — delegates to setup/ subpackage.

All imports from this module continue to work unchanged.
Actual implementation lives in:
  setup.wizard_helpers — config dir, .env writing, URL opening
  setup.wizard_pages   — Welcome, Telegram, MT5, Groups, AI, Finish pages
  setup.wizard_shell   — SetupWizard window frame and navigation
  setup.launcher       — LauncherWindow (shown when .env exists)
"""
from __future__ import annotations

from telegram_signal_copier.setup.wizard_shell import SetupWizard as SetupWizard  # noqa: F401
from telegram_signal_copier.setup.launcher import LauncherWindow as LauncherWindow  # noqa: F401
from telegram_signal_copier.setup.wizard_helpers import (  # noqa: F401
    get_config_dir as _get_config_dir,
    env_path as _env_path,
    write_env as _write_env,
    open_url as _open_url,
)
