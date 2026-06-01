"""Backward-compatibility shim — bridge helpers moved to adapters.bridge.helpers."""
from telegram_signal_copier.adapters.bridge.helpers import (  # noqa: F401
    bridge_append_queue_entry as bridge_append_queue_entry,
    bridge_normalize_execution_result as bridge_normalize_execution_result,
    bridge_payload_text as bridge_payload_text,
    bridge_should_retry_symbol_selection as bridge_should_retry_symbol_selection,
    bridge_strip_symbol_suffix as bridge_strip_symbol_suffix,
    bridge_symbol_retry_candidates as bridge_symbol_retry_candidates,
    bridge_write_command_file as bridge_write_command_file,
)
