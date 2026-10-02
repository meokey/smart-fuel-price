"""Root-level pytest plugin registration.

pytest_homeassistant_custom_component is heavy -- it pulls in the full
homeassistant package, including native-extension dependencies (like
lru-dict) that need a C compiler to build from source. That's not
available in every environment (confirmed: it isn't on this project's
Synology DSM Python). It's only needed for tests/ha/ (marked
"ha_integration", excluded from the default local run -- see
pytest.ini); CI installs it and runs those tests there instead.
Registering it only when it's actually importable means its absence
doesn't break every other test -- which is what happened before this
file existed.
"""

try:
    import pytest_homeassistant_custom_component  # noqa: F401
    pytest_plugins = ["pytest_homeassistant_custom_component"]
except ImportError:
    pytest_plugins = []
