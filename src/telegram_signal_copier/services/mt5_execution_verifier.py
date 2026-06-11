"""MT5 execution verification helpers.

Optional dependency: MetaTrader5. Import lazily so the core pipeline still runs
when the package is not installed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from telegram_signal_copier.models import ExecutionResult, TradeCommand

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MT5VerificationResult:
    verified: bool
    message: str
    account_login: str | None = None
    account_server: str | None = None
    found_ticket: str | None = None
    found_symbol: str | None = None
    found_entry: float | None = None
    found_profit: float | None = None


def verify_execution_result(
    command: TradeCommand,
    result: ExecutionResult,
    login: str | None,
    password: str | None,
    server: str | None,
    timeout_seconds: float = 15.0,
) -> MT5VerificationResult:
    """Verify a bridge result ticket exists in MT5 history.

    Returns a verification result instead of raising so pipeline logging can keep
    the original execution status and surface the sync mismatch.
    """
    if not getattr(result, "ticket", None):
        return MT5VerificationResult(False, "No MT5 ticket returned by bridge")

    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except Exception as exc:
        return MT5VerificationResult(False, f"MetaTrader5 package unavailable: {exc}")

    if result.status not in {"FILLED", "PENDING"}:
        return MT5VerificationResult(False, f"Skipping verification for status={result.status}")

    initialized = False
    try:
        if login and login.strip():
            kwargs: dict[str, Any] = {"login": int(login)}
            if password:
                kwargs["password"] = password
            if server:
                kwargs["server"] = server
            initialized = bool(mt5.initialize(**kwargs))
        else:
            initialized = bool(mt5.initialize())

        if not initialized:
            return MT5VerificationResult(False, f"MT5 initialize failed: {mt5.last_error()}")

        account = mt5.account_info()
        account_login = str(account.login) if account and account.login else None
        account_server = account.server if account else None

        end = datetime.now() + timedelta(days=1)
        start = datetime.fromisoformat(result.executed_at) - timedelta(days=2) if result.executed_at else datetime.now() - timedelta(days=2)

        found: dict[str, Any] | None = None
        for collection_name in ("orders", "deals"):
            getter = getattr(mt5, f"history_{collection_name}_get")
            records = getter(start, end) or []
            for record in records:
                ticket = str(getattr(record, "ticket", ""))
                order = str(getattr(record, "order", ""))
                position_id = str(getattr(record, "position_id", ""))
                if {result.ticket, str(result.ticket)} & {ticket, order, position_id}:
                    found = {
                        "collection": collection_name,
                        "ticket": ticket,
                        "order": order,
                        "position_id": position_id,
                        "symbol": getattr(record, "symbol", ""),
                        "price": getattr(record, "price", None),
                        "profit": getattr(record, "profit", None),
                    }
                    break
            if found:
                break

        if found:
            return MT5VerificationResult(
                verified=True,
                message=f"MT5 history verified {found['collection']} ticket={result.ticket}",
                account_login=account_login,
                account_server=account_server,
                found_ticket=str(found.get("ticket") or result.ticket),
                found_symbol=str(found.get("symbol") or ""),
                found_entry=float(found["price"]) if found.get("price") not in (None, 0.0) else None,
                found_profit=float(found["profit"]) if found.get("profit") not in (None, 0.0) else None,
            )

        return MT5VerificationResult(
            False,
            f"MT5 history does not contain ticket={result.ticket}",
            account_login=account_login,
            account_server=account_server,
            found_ticket=None,
            found_symbol=None,
        )
    except Exception as exc:
        return MT5VerificationResult(False, f"MT5 verification failed: {exc}")
    finally:
        if initialized:
            try:
                mt5.shutdown()
            except Exception:
                logger.debug("MT5 shutdown failed", exc_info=True)
