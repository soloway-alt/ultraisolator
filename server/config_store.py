"""Backward-compatible import shim for the relocated config layer.

The config loading/validation code now lives in ``isolator.config`` (the
engine owns it). This module preserves the historical ``server.config_store``
import path for the server layer and the test suite by re-exporting the
public surface.
"""

from isolator.config import (
    CONFIG_SCHEMA,
    DEFAULT_CONFIG,
    REMOVED_CONFIG_KEYS,
    ConfigError,
    ConfigStore,
)

__all__ = [
    "CONFIG_SCHEMA",
    "DEFAULT_CONFIG",
    "REMOVED_CONFIG_KEYS",
    "ConfigError",
    "ConfigStore",
]
