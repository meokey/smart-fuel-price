"""Offline tests for the comparison-ready notification (#85).

homeassistant isn't installed here, so we stub its modules (enough for
comparison.py to import) and drive record/maybe_notify with a fake hass.
The contract under test: one persistent notification per city, only when
the NRC history AND a forecast-provider sensor cover the same city.
"""
import asyncio
import sys
import types
from pathlib import Path

# ---- stub homeassistant (minimal, enough for comparison.py) ----
ha = types.ModuleType("homeassistant")
ha.__path__ = []
helpers = types.ModuleType("homeassistant.helpers")
helpers.__path__ = []
storage_mod = types.ModuleType("homeassistant.helpers.storage")


class FakeStore:
    """In-memory Store; _backend simulates .storage across restarts."""

    _backend = {}

    def __init__(self, hass, version, key):
        self._key = key

    async def async_load(self):
        return FakeStore._backend.get(self._key)

    async def async_save(self, data):
        FakeStore._backend[self._key] = data


storage_mod.Store = FakeStore
helpers.storage = storage_mod
ha.helpers = helpers
sys.modules.update(
    {
        "homeassistant": ha,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage_mod,
    }
)

# ---- load the real integration modules ----
COMP = Path(__file__).resolve().parents[1] / "custom_components" / "smart_fuel_price"
pkg = types.ModuleType("custom_components")
pkg.__path__ = [str(COMP.parent)]
sfc = types.ModuleType("custom_components.smart_fuel_price")
sfc.__path__ = [str(COMP)]
sys.modules["custom_components"] = pkg
sys.modules["custom_components.smart_fuel_price"] = sfc
import importlib.util

for _name in ["const", "comparison"]:
    _spec = importlib.util.spec_from_file_location(
        f"custom_components.smart_fuel_price.{_name}", COMP / f"{_name}.py"
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"custom_components.smart_fuel_price.{_name}"] = _mod
    _spec.loader.exec_module(_mod)

const = sys.modules["custom_components.smart_fuel_price.const"]
comparison = sys.modules["custom_components.smart_fuel_price.comparison"]
DOMAIN = const.DOMAIN


class FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, service_data, blocking=False):
        self.calls.append((domain, service, service_data))


class FakeHass:
    def __init__(self):
        self.data = {}
        self.services = FakeServices()


# Class names matter: comparison.py matches forecast providers by name.
class AffordableEnergyCaProvider:
    def __init__(self, city):
        self._city = city
        self.name = "Gas Wizard"

    @property
    def city(self):
        return self._city


class CityNewsCaProvider:
    def __init__(self, city):
        self._city = city
        self.name = "CityNews"

    @property
    def city(self):
        return self._city


class NrcanGcCaProvider:
    def __init__(self, city):
        self._city = city
        self.name = "NRC"

    @property
    def city(self):
        return self._city


class FakeSensor:
    def __init__(self, entity_id, value_key):
        self.entity_id = entity_id
        self._value_key = value_key


def _hass_with_entries(*entries):
    """entries: (entry_id, provider, [(entity_id, value_key), ...])."""
    hass = FakeHass()
    by_entry = {}
    for entry_id, provider, sensors in entries:
        device_key = entry_id
        by_entry[entry_id] = {
            device_key: {
                "sensors": [FakeSensor(eid, vk) for eid, vk in sensors],
                "providers": [provider],
            }
        }
    hass.data[DOMAIN] = {"sensors": by_entry}
    return hass


def _reset_store():
    FakeStore._backend.clear()


def test_notify_when_nrc_and_forecast_coexist():
    _reset_store()
    hass = _hass_with_entries(
        ("e1", NrcanGcCaProvider("toronto"), []),
        (
            "e2",
            AffordableEnergyCaProvider("toronto"),
            [
                ("sensor.toronto_today", "current_price"),
                ("sensor.toronto_tomorrow", "tomorrow_price"),
            ],
        ),
    )
    asyncio.run(comparison.record_nrc_history_ready(hass, "toronto", 42))
    assert asyncio.run(comparison.maybe_notify_comparison_ready(hass, "toronto")) is True

    assert len(hass.services.calls) == 1
    domain, service, data = hass.services.calls[0]
    assert domain == "persistent_notification" and service == "create"
    assert data["notification_id"] == f"{DOMAIN}_comparison_toronto"
    assert "Toronto" in data["title"]
    msg = data["message"]
    assert "smart_fuel_price:nrc_weekly_toronto" in msg
    assert "sensor.toronto_today" in msg and "sensor.toronto_tomorrow" in msg
    assert "Gas Wizard" in msg
    assert "type: statistics-graph" in msg
    # The message guides a novice: steps + docs hyperlink (#88).
    assert "Add the comparison card" in msg
    assert "Manual" in msg
    assert "Dashboard-cards.md" in msg
    assert "github.com/meokey/smart-fuel-price" in msg


def test_notify_only_once_per_city():
    _reset_store()
    hass = _hass_with_entries(
        ("e2", CityNewsCaProvider("toronto"), [("sensor.cn_toronto", "state")]),
    )
    asyncio.run(comparison.record_nrc_history_ready(hass, "toronto", 42))
    assert asyncio.run(comparison.maybe_notify_comparison_ready(hass, "toronto")) is True
    # Second call (e.g. next poll) stays silent...
    assert asyncio.run(comparison.maybe_notify_comparison_ready(hass, "toronto")) is False
    assert len(hass.services.calls) == 1
    # ...and survives a restart (state is in the Store backend).
    hass2 = _hass_with_entries(
        ("e2", CityNewsCaProvider("toronto"), [("sensor.cn_toronto", "state")]),
    )
    assert asyncio.run(comparison.maybe_notify_comparison_ready(hass2, "toronto")) is False
    assert len(hass2.services.calls) == 0


def test_no_notify_without_forecast_sibling():
    _reset_store()
    hass = _hass_with_entries(("e1", NrcanGcCaProvider("toronto"), []))
    asyncio.run(comparison.record_nrc_history_ready(hass, "toronto", 42))
    assert asyncio.run(comparison.maybe_notify_comparison_ready(hass, "toronto")) is False
    assert hass.services.calls == []


def test_no_notify_without_nrc_history():
    _reset_store()
    hass = _hass_with_entries(
        (
            "e2",
            AffordableEnergyCaProvider("toronto"),
            [("sensor.toronto_today", "current_price")],
        ),
    )
    assert asyncio.run(comparison.maybe_notify_comparison_ready(hass, "toronto")) is False
    assert hass.services.calls == []


def test_no_notify_for_different_cities():
    _reset_store()
    hass = _hass_with_entries(
        ("e1", NrcanGcCaProvider("toronto"), []),
        (
            "e2",
            AffordableEnergyCaProvider("vancouver"),
            [("sensor.van_today", "current_price")],
        ),
    )
    asyncio.run(comparison.record_nrc_history_ready(hass, "toronto", 42))
    assert asyncio.run(comparison.maybe_notify_comparison_ready(hass, "toronto")) is False
    assert asyncio.run(comparison.maybe_notify_comparison_ready(hass, "vancouver")) is False
    assert hass.services.calls == []


def test_record_ignores_zero_weeks():
    _reset_store()
    hass = FakeHass()
    asyncio.run(comparison.record_nrc_history_ready(hass, "toronto", 0))
    assert FakeStore._backend == {}


def test_notify_failure_never_raises():
    _reset_store()

    class BrokenServices:
        async def async_call(self, *args, **kwargs):
            raise RuntimeError("boom")

    hass = _hass_with_entries(
        ("e2", CityNewsCaProvider("toronto"), [("sensor.cn_toronto", "state")]),
    )
    hass.services = BrokenServices()
    asyncio.run(comparison.record_nrc_history_ready(hass, "toronto", 42))
    # Must not raise; returns False.
    assert asyncio.run(comparison.maybe_notify_comparison_ready(hass, "toronto")) is False
