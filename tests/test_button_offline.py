"""Offline tests for the Manual refresh button.

homeassistant isn't installed here, so we stub its modules (enough for
button.py to import) and drive SmartFuelRefreshButton.async_press with
fake sensors. The contract under test: one forced fetch per unique
provider -- not one per sensor -- then every sensor re-reads from the
warmed cache.
"""
import asyncio
import sys
import types
from pathlib import Path

# ---- stub homeassistant (minimal, enough for button.py) ----
ha = types.ModuleType("homeassistant"); ha.__path__ = []
components = types.ModuleType("homeassistant.components"); components.__path__ = []
button_mod = types.ModuleType("homeassistant.components.button")


class ButtonEntity:
    pass


button_mod.ButtonEntity = ButtonEntity
components.button = button_mod
ha.components = components
helpers = types.ModuleType("homeassistant.helpers"); helpers.__path__ = []
devreg = types.ModuleType("homeassistant.helpers.device_registry")
devreg.DeviceInfo = lambda **kwargs: kwargs
helpers.device_registry = devreg
event_mod = types.ModuleType("homeassistant.helpers.event")
scheduled_calls = []


def fake_call_later(hass, delay, callback):
    scheduled_calls.append((delay, callback))
    return lambda: None


event_mod.async_call_later = fake_call_later
helpers.event = event_mod
ha.helpers = helpers
sys.modules.update(
    {
        "homeassistant": ha,
        "homeassistant.components": components,
        "homeassistant.components.button": button_mod,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.device_registry": devreg,
        "homeassistant.helpers.event": event_mod,
    }
)

# ---- load the real integration modules ----
COMP = Path(__file__).resolve().parents[1] / "custom_components" / "smart_fuel_price"
pkg = types.ModuleType("custom_components"); pkg.__path__ = [str(COMP.parent)]
sfc = types.ModuleType("custom_components.smart_fuel_price"); sfc.__path__ = [str(COMP)]
sys.modules["custom_components"] = pkg
sys.modules["custom_components.smart_fuel_price"] = sfc
import importlib.util

for _name in ["const", "button"]:
    _spec = importlib.util.spec_from_file_location(
        f"custom_components.smart_fuel_price.{_name}", COMP / f"{_name}.py"
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"custom_components.smart_fuel_price.{_name}"] = _mod
    _spec.loader.exec_module(_mod)

button = sys.modules["custom_components.smart_fuel_price.button"]


class FakeSensor:
    def __init__(self, provider):
        self._provider = provider
        self.force_calls = 0
        self.update_calls = 0

    async def async_force_refresh(self):
        self.force_calls += 1

    async def async_update(self):
        self.update_calls += 1


def _pressable_button(*sensors):
    """Button with the HA bits async_press needs (hass, state write)."""
    btn = button.SmartFuelRefreshButton("k", "Device", list(sensors))
    btn.hass = object()
    btn.writes = 0
    btn.async_write_ha_state = lambda: setattr(btn, "writes", btn.writes + 1)
    return btn


def test_press_fetches_once_per_unique_provider():
    provider_a, provider_b = object(), object()
    s1, s2 = FakeSensor(provider_a), FakeSensor(provider_a)
    s3 = FakeSensor(provider_b)
    btn = _pressable_button(s1, s2, s3)
    asyncio.run(btn.async_press())
    # One forced fetch per provider, not per sensor...
    assert (s1.force_calls, s2.force_calls, s3.force_calls) == (1, 0, 1)
    # ...but every sensor re-reads from the warmed cache.
    assert s1.update_calls == s2.update_calls == s3.update_calls == 1


def test_press_with_no_sensors_does_not_raise():
    btn = _pressable_button()
    asyncio.run(btn.async_press())


def test_available_before_press():
    btn = _pressable_button()
    assert btn.available is True
    assert btn.extra_state_attributes["next_available_at"] is None


def test_press_starts_cooldown():
    s1 = FakeSensor(object())
    btn = _pressable_button(s1)
    asyncio.run(btn.async_press())
    assert s1.force_calls == 1
    assert btn.available is False
    assert btn.extra_state_attributes["next_available_at"] is not None
    # A second press during the cooldown is ignored, not queued.
    asyncio.run(btn.async_press())
    assert s1.force_calls == 1


def test_cooldown_reenables_button():
    scheduled_calls.clear()
    s1 = FakeSensor(object())
    btn = _pressable_button(s1)
    asyncio.run(btn.async_press())
    assert btn.available is False
    assert len(scheduled_calls) == 1
    delay, callback = scheduled_calls[0]
    assert delay == 60
    asyncio.run(callback(None))  # cooldown timer fires
    assert btn.available is True
    assert btn.extra_state_attributes["next_available_at"] is None
    # Pressing again works after the cooldown.
    asyncio.run(btn.async_press())
    assert s1.force_calls == 2
