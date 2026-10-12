"""Offline tests for the buy-now decision logic (issue #50).

homeassistant isn't installed here, so we stub its modules (enough for
binary_sensor to import) and drive the real _decide() with fake providers.
"""
import asyncio
import importlib.util
import sys
import types
from datetime import timedelta
from pathlib import Path

import pytest

INTEGRATION_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "smart_fuel_price"
)

# ---- stub homeassistant ----
ha = types.ModuleType("homeassistant")
ha.__path__ = []
sys.modules["homeassistant"] = ha

comp = types.ModuleType("homeassistant.components")
comp.__path__ = []
sys.modules["homeassistant.components"] = comp
ha.components = comp

bs_mod = types.ModuleType("homeassistant.components.binary_sensor")


class BinarySensorEntity:
    pass


bs_mod.BinarySensorEntity = BinarySensorEntity
sys.modules["homeassistant.components.binary_sensor"] = bs_mod

ce = types.ModuleType("homeassistant.config_entries")
ce.ConfigEntry = object
sys.modules["homeassistant.config_entries"] = ce

core = types.ModuleType("homeassistant.core")
core.HomeAssistant = object
sys.modules["homeassistant.core"] = core

helpers = types.ModuleType("homeassistant.helpers")
helpers.__path__ = []
sys.modules["homeassistant.helpers"] = helpers

entity = types.ModuleType("homeassistant.helpers.entity")


class DeviceInfo(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


entity.DeviceInfo = DeviceInfo
sys.modules["homeassistant.helpers.entity"] = entity

plat = types.ModuleType("homeassistant.helpers.entity_platform")
plat.AddEntitiesCallback = object
sys.modules["homeassistant.helpers.entity_platform"] = plat

er_mod = types.ModuleType("homeassistant.helpers.entity_registry")
er_mod.async_get = lambda hass: hass._registry
sys.modules["homeassistant.helpers.entity_registry"] = er_mod

# ---- load the integration package stand-in ----
pkg = types.ModuleType("sfp_integration")
pkg.__path__ = [str(INTEGRATION_DIR)]
sys.modules["sfp_integration"] = pkg

spec_const = importlib.util.spec_from_file_location(
    "sfp_integration.const", INTEGRATION_DIR / "const.py"
)
const = importlib.util.module_from_spec(spec_const)
sys.modules["sfp_integration.const"] = const
spec_const.loader.exec_module(const)

spec = importlib.util.spec_from_file_location(
    "sfp_integration.binary_sensor", INTEGRATION_DIR / "binary_sensor.py"
)
binary_sensor = importlib.util.module_from_spec(spec)
sys.modules["sfp_integration.binary_sensor"] = binary_sensor
spec.loader.exec_module(binary_sensor)

_decide = binary_sensor._decide


class FakeProvider:
    def __init__(self, data=None, exc=None):
        self._data = data or {}
        self._exc = exc

    def get_data(self):
        if self._exc:
            raise self._exc
        return self._data


def test_rising_means_buy_now():
    buy, delta, details = _decide(
        [FakeProvider({"tomorrow_price": 185.9, "current_price": 182.9})]
    )
    assert buy is True
    assert delta == pytest.approx(3.0)
    assert details["tomorrow_price"] == 185.9


def test_falling_means_wait():
    buy, delta, _ = _decide(
        [FakeProvider({"tomorrow_price": 180.0, "current_price": 182.9})]
    )
    assert buy is False
    assert delta == pytest.approx(-2.9)


def test_flat_means_wait():
    buy, delta, _ = _decide(
        [FakeProvider({"tomorrow_price": 182.9, "current_price": 182.9})]
    )
    assert buy is False
    assert delta == pytest.approx(0.0)


def test_no_forecast_is_unknown():
    # GasBuddy pure current-price layout has no tomorrow_price.
    buy, delta, _ = _decide([FakeProvider({"current_price": 168.4})])
    assert buy is None
    assert delta is None


def test_first_provider_with_forecast_wins():
    providers = [
        FakeProvider({"current_price": 168.4}),  # no forecast -> skipped
        FakeProvider({"tomorrow_price": 190.0, "current_price": 185.0}),
    ]
    buy, delta, _ = _decide(providers)
    assert buy is True
    assert delta == pytest.approx(5.0)


def test_provider_exception_is_skipped():
    providers = [
        FakeProvider(exc=RuntimeError("boom")),
        FakeProvider({"tomorrow_price": 180.0, "current_price": 185.0}),
    ]
    buy, delta, _ = _decide(providers)
    assert buy is False


def test_all_unknown_when_nothing_usable():
    buy, delta, _ = _decide([FakeProvider({}), FakeProvider(exc=ValueError("x"))])
    assert buy is None
    assert delta is None


# ---- issue #61: only forecast-capable devices get a Buy-now sensor ----

class NoForecastProvider:
    supports_forecast = False


class ForecastProvider:
    supports_forecast = True


def test_device_has_forecast():
    assert binary_sensor._device_has_forecast([ForecastProvider()]) is True
    assert binary_sensor._device_has_forecast([NoForecastProvider()]) is False
    # mixed device: one forecast-capable provider is enough
    assert (
        binary_sensor._device_has_forecast([NoForecastProvider(), ForecastProvider()])
        is True
    )
    # fail-open: providers without the flag keep the old behavior
    assert binary_sensor._device_has_forecast([FakeProvider({})]) is True
    assert binary_sensor._device_has_forecast([]) is False


class FakeRegistry:
    def __init__(self):
        self._entries = {}
        self.removed = []

    def async_get_entity_id(self, platform, domain, unique_id):
        return self._entries.get((platform, domain, unique_id))

    def async_remove(self, entity_id):
        self.removed.append(entity_id)


class FakeHass:
    def __init__(self, by_device):
        self.data = {"smart_fuel_price": {"sensors": {"entry1": by_device}}}
        self._registry = FakeRegistry()


class FakeEntry:
    entry_id = "entry1"


def test_setup_entry_skips_forecast_less_devices_and_cleans_registry():
    async def go():
        hass = FakeHass(
            {
                "dev_forecast": {
                    "name": "Toronto",
                    "providers": [ForecastProvider()],
                },
                "dev_snapshot": {
                    "name": "Calgary",
                    "providers": [NoForecastProvider()],
                },
            }
        )
        # stale entry left by a previous version on the snapshot device
        hass._registry._entries[
            ("binary_sensor", "smart_fuel_price", "dev_snapshot_buy_now")
        ] = "binary_sensor.calgary_buy_now"
        added = []
        await binary_sensor.async_setup_entry(
            hass,
            FakeEntry(),
            lambda entities, update_before_add=False: added.extend(entities),
        )
        assert [e._attr_unique_id for e in added] == ["dev_forecast_buy_now"]
        assert hass._registry.removed == ["binary_sensor.calgary_buy_now"]

    asyncio.run(go())


def test_setup_entry_with_real_providers():
    """Calgary (gasbuddy layout) skipped, Toronto (forecast) kept."""
    from sfp_providers.citynews_ca import CityNewsCaProvider

    async def go():
        hass = FakeHass(
            {
                "dev_toronto": {
                    "name": "Toronto",
                    "providers": [CityNewsCaProvider("toronto")],
                },
                "dev_calgary": {
                    "name": "Calgary",
                    "providers": [CityNewsCaProvider("calgary")],
                },
            }
        )
        added = []
        await binary_sensor.async_setup_entry(
            hass,
            FakeEntry(),
            lambda entities, update_before_add=False: added.extend(entities),
        )
        assert [e._attr_unique_id for e in added] == ["dev_toronto_buy_now"]

    asyncio.run(go())
