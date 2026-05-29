"""Shared pytest fixtures for the Telegram Signal Copier test suite."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from telegram_signal_copier.config import AppConfig


@pytest.fixture()
def tmp_project_root(tmp_path: Path) -> Path:
    """A temporary project root directory for tests that need filesystem access."""
    (tmp_path / "runtime").mkdir()
    (tmp_path / "bridge").mkdir()
    (tmp_path / "bridge" / "outbox").mkdir()
    return tmp_path


@pytest.fixture()
def minimal_config(tmp_project_root: Path) -> AppConfig:
    """A minimal :class:`AppConfig` that requires no real credentials.

    Suitable for unit tests that instantiate services but don't talk to
    Telegram, OpenAI, or MT5.
    """
    bridge_root = tmp_project_root / "bridge"
    return AppConfig(
        project_root=tmp_project_root,
        bridge_inbox_dir=bridge_root,
        bridge_outbox_dir=bridge_root / "outbox",
        telegram_api_id="12345",
        telegram_api_hash="deadbeef",
        telegram_phone_number="+10000000000",
        telegram_session_name="test-session",
        telegram_sources=["TestChannel::9876543210"],
        openai_api_key=None,
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        minimum_confidence=0.70,
        default_volume=0.01,
        allowed_symbols=["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "ETHUSD"],
        dry_run=True,
        approval_required_below=0.85,
        poll_interval_seconds=2.0,
        minimum_rr_ratio=1.5,
    )
