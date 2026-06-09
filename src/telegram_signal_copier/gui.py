"""Backward-compatible facade — delegates to gui/ subpackage.

All imports from this module continue to work unchanged.
Actual implementation lives in:
  gui.dashboard     — SignalCopierDashboard (orchestrator)
  gui.trades_panel  — Trades table, P&L chart, demo data
  gui.channels_panel — Left sidebar, channel toggle/delete/search
  gui.status_panel  — Right sidebar, connection status, metrics
  gui.dialogs       — Add channel dialog, settings dialog
  gui.theme         — Color constants, page setup helpers
"""
from __future__ import annotations

from telegram_signal_copier.gui.dashboard import SignalCopierDashboard as SignalCopierDashboard  # noqa: F401
