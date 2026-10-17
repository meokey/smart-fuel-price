"""Offline tests for the #55 retry scheduler in sensor.py.

homeassistant isn't installed here, so we stub its modules (same pattern
as test_button_offline.py) and drive _update_retry_schedule with a fake
hass: async_add_executor_job runs inline, async_call_later captures.
The contract under test: one retry per provider (shared across sibling
sensors), backoff delay, daily-cap persistence, sensor refresh on fire,
and cancel-on-success / cancel-on-unload.
"""

import asyncio
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

# ---- stub homeassistant (minimal, enough for sensor.py) ----
ha = types.ModuleType("homeassistant")
ha.__path__ = []
components = types.ModuleType("homeassistant.components")
components.__path__ = []
sensor_mod_stub = types.ModuleType("homeassistant.components.sensor")


class SensorEntity:
    pass


class SensorStateClass:
    MEASUREMENT = "measurement"


class SensorDeviceClass:
    TIMESTAMP = "timestamp"
    ENUM = "enum"


sensor_mod_stub.SensorEntity = SensorEntity
sensor_mod_stub.SensorStateClass = SensorStateClass
sensor_mod_stub.SensorDeviceClass = SensorDeviceClass
components.sensor = sensor_mod_stub
ha.components = components

helpers = types.ModuleType("homeassistant.helpers")
helpers.__path__ = []
devreg = types.ModuleType("homeassistant.helpers.device_registry")
devreg.DeviceInfo = lambda **kwargs: kwargs
helpers.device_registry = devreg

event_mod = types.ModuleType("homeassistant.helpers.event")


class FakeHass:
    def __init__(self):
        self.data = {}
        self.scheduled = []  # [delay, callback]

    async def async_add_executor_job(self, func, *args):
        # Yield like the real executor hop so gather() truly interleaves.
        await asyncio.sleep(0)
        return func(*args)


def fake_call_later(hass, delay, callback):
    hass.scheduled.append([delay, callback])

    def cancel():
        hass.scheduled[:] = [s for s in hass.scheduled if s[1] is not callback]

    return cancel


event_mod.async_call_later = fake_call_later
helpers.event = event_mod

storage_mod = types.ModuleType("homeassistant.helpers.storage")


class FakeStore:
    saved = {}

    def __init__(self, hass, version, key):
        self.key = key

    async def async_load(self):
        return FakeStore.saved.get(self.key)

    async def async_save(self, data):
        FakeStore.saved[self.key] = dict(data)


storage_mod.Store = FakeStore
helpers.storage = storage_mod
ha.helpers = helpers

const_mod = types.ModuleType("homeassistant.const")
const_mod.CONF_NAME = "name"
ha.const = const_mod

sys.modules.update(
    {
        "homeassistant": ha,
        "homeassistant.components": components,
        "homeassistant.components.sensor": sensor_mod_stub,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.device_registry": devreg,
        "homeassistant.helpers.event": event_mod,
        "homeassistant.helpers.storage": storage_mod,
        "homeassistant.const": const_mod,
    }
)

# ---- load the real integration modules (stub package, no HA import) ----
COMP = Path(__file__).resolve().parents[1] / "custom_components" / "smart_fuel_price"
pkg = types.ModuleType("custom_components")
pkg.__path__ = [str(COMP.parent)]
sfc = types.ModuleType("custom_components.smart_fuel_price")
sfc.__path__ = [str(COMP)]
sys.modules["custom_components"] = pkg
sys.modules["custom_components.smart_fuel_price"] = sfc
import importlib.util


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f"custom_components.smart_fuel_price.{name}", COMP / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"custom_components.smart_fuel_price.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


const = _load("const")
sensor = _load("sensor")
base = sys.modules["custom_components.smart_fuel_price.providers.base"]
affordable = sys.modules["custom_components.smart_fuel_price.providers.affordableenergy_ca"]


class RetryTestProvider(affordable.AffordableEnergyCaProvider):
    _ROBOTS_TXT_URL = None
    _ROBOTS_CHECK_URL = None


class FakeSensor:
    def __init__(self, provider, hass):
        self._provider = provider
        self.hass = hass
        self.updated = 0
        self._on_remove = []

    async def async_update(self):
        self.updated += 1

    def async_on_remove(self, func):
        self._on_remove.append(func)


def _failed_provider(hass):
    p = RetryTestProvider("toronto")
    p._last_fetch_status = "error"
    p._consec_failures = 1
    return p


def test_schedules_retry_on_failure():
    hass = FakeHass()
    provider = _failed_provider(hass)
    s = FakeSensor(provider, hass)
    asyncio.run(sensor._update_retry_schedule(s))
    assert len(hass.scheduled) == 1
    delay, _cb = hass.scheduled[0]
    assert delay == 15 * 60
    assert provider._retry_handle is not None


def test_no_double_schedule_across_sibling_sensors():
    hass = FakeHass()
    provider = _failed_provider(hass)
    s1, s2 = FakeSensor(provider, hass), FakeSensor(provider, hass)
    asyncio.run(sensor._update_retry_schedule(s1))
    asyncio.run(sensor._update_retry_schedule(s2))
    assert len(hass.scheduled) == 1


def test_concurrent_schedules_still_single_retry():
    hass = FakeHass()
    provider = _failed_provider(hass)
    sensors = [FakeSensor(provider, hass) for _ in range(3)]

    async def go():
        await asyncio.gather(
            *(sensor._update_retry_schedule(s) for s in sensors)
        )

    asyncio.run(go())
    assert len(hass.scheduled) == 1


def test_no_schedule_when_healthy():
    hass = FakeHass()
    provider = RetryTestProvider("toronto")
    provider._last_fetch_status = "ok"
    s = FakeSensor(provider, hass)
    asyncio.run(sensor._update_retry_schedule(s))
    assert hass.scheduled == []


def test_cancel_on_success():
    hass = FakeHass()
    provider = _failed_provider(hass)
    s = FakeSensor(provider, hass)
    asyncio.run(sensor._update_retry_schedule(s))
    assert len(hass.scheduled) == 1
    provider._last_fetch_status = "ok"
    asyncio.run(sensor._update_retry_schedule(s))
    assert hass.scheduled == []
    assert provider._retry_handle is None


def test_cap_blocks_scheduling():
    hass = FakeHass()
    provider = _failed_provider(hass)
    for _ in range(5):
        provider.record_retry()
    s = FakeSensor(provider, hass)
    asyncio.run(sensor._update_retry_schedule(s))
    assert hass.scheduled == []


def test_do_retry_refreshes_sensors_and_persists():
    hass = FakeHass()
    FakeStore.saved.clear()
    provider = _failed_provider(hass)
    s1, s2 = FakeSensor(provider, hass), FakeSensor(provider, hass)
    provider._sensors.extend([s1, s2])

    calls = {}

    def fake_get_data(force=False):
        calls["force"] = force
        provider._last_fetch_status = "ok"
        provider._consec_failures = 0
        return {"is_valid": True, "from_cache": False}

    provider.get_data = fake_get_data
    asyncio.run(sensor._update_retry_schedule(s1))
    assert len(hass.scheduled) == 1
    _, cb = hass.scheduled[0]
    asyncio.run(cb(None))  # fire the retry

    assert calls.get("force") is True
    assert s1.updated == 1 and s2.updated == 1
    assert provider._retry_handle is None
    saved = FakeStore.saved.get(sensor._RETRY_COUNTERS_KEY)
    assert saved[provider.cache_key]["count"] == 1


def test_do_retry_skipped_when_cap_reached_before_fire():
    hass = FakeHass()
    FakeStore.saved.clear()
    provider = _failed_provider(hass)
    s = FakeSensor(provider, hass)
    provider._sensors.append(s)

    fired = []

    def fake_get_data(force=False):
        fired.append(True)
        return {}

    provider.get_data = fake_get_data
    asyncio.run(sensor._update_retry_schedule(s))
    # Cap gets hit before the timer fires (e.g. another path recorded).
    for _ in range(5):
        provider.record_retry()
    _, cb = hass.scheduled[0]
    asyncio.run(cb(None))
    assert fired == []
    assert s.updated == 0


def test_wire_retry_providers():
    hass = FakeHass()
    FakeStore.saved.clear()
    today = datetime.now(timezone.utc).date().isoformat()
    provider = RetryTestProvider("toronto")
    FakeStore.saved[sensor._RETRY_COUNTERS_KEY] = {
        provider.cache_key: {"date": today, "count": 2}
    }

    class Meta:
        def __init__(self, providers):
            self._providers = list(providers)
            self._on_remove = []

        async def async_update(self):
            pass

        def async_on_remove(self, func):
            self._on_remove.append(func)

    s1 = FakeSensor(provider, hass)
    meta = Meta([provider])
    counters = asyncio.run(sensor._load_retry_counters(hass))
    sensor._wire_retry_providers([s1, meta], counters)

    assert s1 in provider._sensors and meta in provider._sensors
    assert provider._retry_state == {"date": today, "count": 2}
    # Unload hook registered exactly once for the provider.
    assert len(meta._on_remove) + len(s1._on_remove) == 1
