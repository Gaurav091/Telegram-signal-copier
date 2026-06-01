"""Backward-compatibility shim — provider adapters moved to adapters.ai.providers."""
from telegram_signal_copier.adapters.ai.providers import (  # noqa: F401
    CerebrasAdapter as CerebrasAdapter,
    CloudflareAdapter as CloudflareAdapter,
    GroqAdapter as GroqAdapter,
    NvidiaAdapter as NvidiaAdapter,
    OpenAIAdapter as OpenAIAdapter,
    ProviderAdapter as ProviderAdapter,
    get_adapter as get_adapter,
)
