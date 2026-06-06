"""Type stubs for telethon.errors."""

from __future__ import annotations

class FloodWaitError(Exception):
    seconds: int
