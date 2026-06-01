"""Backward-compatibility shim — ClusterSignal / parse_cluster moved to services.clustering.parser."""
from telegram_signal_copier.services.clustering.parser import (  # noqa: F401
    ClusterSignal as ClusterSignal,
    auto_derive_sl as auto_derive_sl,
    parse_cluster as parse_cluster,
)
