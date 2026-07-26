"""Backward-compatible wrapper for the modular Esports Isolator package."""

from isolator import winapi as _winapi
from isolator.app import EsportsIsolatorPro
from isolator.cli import main

# Deliberate compat shim: winapi defines an explicit __all__, so this star
# import re-exports exactly the curated Win32/domain surface (no stdlib leaks).
from isolator.winapi import *

__all__ = sorted(set(_winapi.__all__) | {"EsportsIsolatorPro", "main"})


if __name__ == "__main__":
    raise SystemExit(main())
