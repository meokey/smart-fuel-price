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

try:
    import pytest_socket  # noqa: F401
    _HAS_PYTEST_SOCKET = True
except ImportError:
    _HAS_PYTEST_SOCKET = False

if _HAS_PYTEST_SOCKET:
    @pytest.fixture(autouse=True)
    def _allow_real_network(socket_enabled):
        """pytest-homeassistant-custom-component (when installed, e.g.
        in CI) pulls in pytest-socket, which blocks real network access
        by default for the whole session. test_live.py in this
        directory deliberately hits real websites -- requesting
        pytest-socket's own socket_enabled fixture re-allows it."""
else:
    @pytest.fixture(autouse=True)
    def _allow_real_network():
        """pytest-socket isn't installed (e.g. locally on this NAS), so
        there's nothing blocking real network access to begin with --
        nothing to do here."""
        yield
