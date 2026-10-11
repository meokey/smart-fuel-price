"""Offline tests for the buy-now decision logic (issue #50).

homeassistant isn't installed here, so we stub its modules (enough for
binary_sensor to import) and drive the real _decide() with fake providers.
"""
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
