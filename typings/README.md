# Type Stubs (`typings/`)

This directory contains minimal Python type stub (`.pyi`) files for third-party
libraries that do not provide their own PEP 561 type annotations.  These stubs
are used by **Pyrefly** (and other static type checkers like Pyright) to
resolve types in the project without relying on the library's internal
type information.

## Contents

| Directory | Library | Purpose |
|-----------|---------|---------|
| `telethon/` | [Telethon](https://github.com/LonamiWebs/Telethon) | Async Telegram client — defines `TelegramClient` with async context manager protocol, events, errors, sessions, and TL types |
| `MetaTrader5/` | [MetaTrader5](https://pypi.org/project/MetaTrader5/) | Python wrapper for the MT5 terminal — defines `initialize`, `account_info`, `order_send`, `positions_get`, `history_deals_get`, etc. |

## Usage

Pyrefly automatically discovers these stubs when they are placed in a `typings/`
directory at the project root — no additional configuration is needed.

## Notes

- These stubs are **minimal** — they only cover the API surface used by this project.
- They are not intended as complete stubs for general Telethon or MT5 use.
- If either library ships official type stubs in the future, this directory can be removed.
