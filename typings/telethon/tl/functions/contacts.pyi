"""Type stubs for telethon.tl.functions.contacts."""

from __future__ import annotations

class SearchRequest:
    q: str
    limit: int

    def __init__(self, q: str, limit: int = ...) -> None: ...
