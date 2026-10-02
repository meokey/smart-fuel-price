"""Test bootstrap: load provider modules without importing the integration.

Importing ``custom_components.smart_fuel_price.providers`` first executes
``custom_components/smart_fuel_price/__init__.py``, which imports
``homeassistant`` -- not installed for these lightweight tests (locally
or in CI). The provider modules only need ``requests`` and each other, so
we register a stand-in package pointing at the providers folder. Tests
then use ``from sfp_providers import vendor_widgets``.
"""

import sys
import types
from pathlib import Path

import pytest

PROVIDERS_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "smart_fuel_price"
    / "providers"
)

_pkg = types.ModuleType("sfp_providers")
_pkg.__path__ = [str(PROVIDERS_DIR)]
sys.modules["sfp_providers"] = _pkg
