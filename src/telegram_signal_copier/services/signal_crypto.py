"""Backward-compatibility shim — crypto functions moved to services.signals.crypto."""
from telegram_signal_copier.services.signals.crypto import (  # noqa: F401
    recover_crypto_entry_from_text as recover_crypto_entry_from_text,
    repair_crypto_entry_price as repair_crypto_entry_price,
)
