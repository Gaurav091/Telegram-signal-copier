"""Backward-compatibility shim — utility functions moved to adapters.ai.utils."""
from telegram_signal_copier.adapters.ai.utils import (  # noqa: F401
    build_providers as build_providers,
    compute_cache_key as compute_cache_key,
    image_data_url as image_data_url,
    json_from_text as json_from_text,
)
