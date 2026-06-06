"""Type stubs for MetaTrader5."""

from __future__ import annotations

from typing import Any

def initialize(
    login: int | None = ...,
    password: str | None = ...,
    server: str | None = ...,
    path: str | None = ...,
    portable: bool | None = ...,
) -> bool: ...

def login(
    login: int,
    password: str,
    server: str | None = ...,
) -> bool: ...

def shutdown() -> None: ...

def last_error() -> tuple[int, str]: ...

def account_info() -> AccountInfo | None: ...

def symbol_info_tick(symbol: str) -> Tick | None: ...

def symbol_info(symbol: str) -> SymbolInfo | None: ...

def copy_rates_from_pos(
    symbol: str,
    timeframe: int,
    start_pos: int,
    count: int,
) -> list[dict[str, Any]] | None: ...

def order_send(request: dict[str, Any]) -> OrderSendResult: ...

def order_calc_margin(
    action: int,
    symbol: str,
    volume: float,
    price: float,
) -> float: ...

def order_calc_profit(
    action: int,
    symbol: str,
    volume: float,
    price_open: float,
    price_close: float,
) -> float: ...

def positions_get(symbol: str | None = ...) -> tuple[Position, ...] | None: ...

def history_deals_get(
    date_from: int,
    date_to: int,
    symbol: str | None = ...,
) -> tuple[Deal, ...] | None: ...

class AccountInfo:
    login: int
    balance: float
    equity: float
    margin: float
    margin_free: float
    margin_level: float
    profit: float
    name: str
    server: str
    currency: str
    company: str
    trade_mode: int
    leverage: int
    limit_orders: int

class Tick:
    symbol: str
    time: int
    bid: float
    ask: float
    last: float
    volume: int
    flags: int

class SymbolInfo:
    name: str
    point: float
    digits: int
    spread: float
    trade_mode: int
    trade_exec_mode: int
    trade_stops_level: int
    volume_min: float
    volume_max: float
    volume_step: float

class Position:
    ticket: int
    symbol: str
    type: int
    volume: float
    price_open: float
    sl: float
    tp: float
    profit: float
    commission: float
    swap: float
    time: int
    magic: int
    comment: str

class Deal:
    ticket: int
    symbol: str
    type: int
    volume: float
    price: float
    profit: float
    commission: float
    swap: float
    time: int
    magic: int
    comment: str
    entry: int

class OrderSendResult:
    retcode: int
    deal: int
    order: int
    volume: float
    price: float
    comment: str
    request_id: int
    retcode_external: int
    request: Any
