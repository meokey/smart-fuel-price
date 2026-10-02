"""Fixtures for the Home-Assistant-aware test suite (config_flow.py,
sensor.py). These need the real `homeassistant` package via
pytest-homeassistant-custom-component -- kept in their own subdirectory
so the rest of tests/ (which deliberately avoids homeassistant, see
tests/conftest.py) is unaffected.
"""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """HA's test harness ignores custom_components/ by default, to stop
    HA core's own test suite from picking up arbitrary custom
    integrations. Requesting enable_custom_integrations switches that
    off so our integration actually loads during these tests."""
    yield
