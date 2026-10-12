"""Offline tests for config_flow._get_cities_for_provider resilience.

homeassistant isn't installed here, so we stub its modules (enough for
config_flow to import) and drive the real _get_cities_for_provider with a
fake hass. The contract under test: the function NEVER raises -- any
failure in discovery, filtering or storage falls back to the provider's
static curated list, and the failure is logged.
"""
import asyncio
import logging
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# ---- stub homeassistant (mirrors tests/ha expectations, minimal) ----
ha = types.ModuleType("homeassistant"); ha.__path__ = []
ce = types.ModuleType("homeassistant.config_entries")


class ConfigFlow:
    def __init_subclass__(cls, domain=None, **kw):
        super().__init_subclass__(**kw)


ce.ConfigFlow = ConfigFlow


class OptionsFlow:
    pass


ce.OptionsFlow = OptionsFlow
ha.config_entries = ce
core = types.ModuleType("homeassistant.core")
core.callback = lambda f: f
ha.core = core
helpers = types.ModuleType("homeassistant.helpers"); helpers.__path__ = []
storage = types.ModuleType("homeassistant.helpers.storage")


class Store:
    _db = {}

    def __init__(self, hass, version, key):
        self.key = (version, key)

    async def async_load(self):
        return Store._db.get(self.key)

    async def async_save(self, data):
        Store._db[self.key] = data


storage.Store = Store
helpers.storage = storage
selmod = types.ModuleType("homeassistant.helpers.selector")
selmod.NumberSelector = type("NumberSelector", (), {"__init__": lambda self, c: None})
selmod.NumberSelectorConfig = type(
    "NumberSelectorConfig", (), {"__init__": lambda self, **kw: None}
)
helpers.selector = selmod
cvmod = types.ModuleType("homeassistant.helpers.config_validation")
cvmod.multi_select = lambda opts: opts
helpers.config_validation = cvmod
ha.helpers = helpers
sys.modules.update(
    {
        "homeassistant": ha,
        "homeassistant.config_entries": ce,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage,
        "homeassistant.helpers.selector": selmod,
        "homeassistant.helpers.config_validation": cvmod,
    }
)

# ---- stub voluptuous (config_flow imports it; CI's env doesn't have it) ----
volmod = types.ModuleType("voluptuous")


def _vol_dummy(*args, **kwargs):
    class _D:
        def __call__(self, *a, **k):
            return _D()

    return _D()


for _n in ("Schema", "Required", "Optional", "In"):
    setattr(volmod, _n, _vol_dummy)
sys.modules["voluptuous"] = volmod

# ---- load the real integration modules ----
COMP = Path(__file__).resolve().parents[1] / "custom_components" / "smart_fuel_price"
pkg = types.ModuleType("custom_components"); pkg.__path__ = [str(COMP.parent)]
sfc = types.ModuleType("custom_components.smart_fuel_price"); sfc.__path__ = [str(COMP)]
sys.modules["custom_components"] = pkg
sys.modules["custom_components.smart_fuel_price"] = sfc
prov = types.ModuleType("custom_components.smart_fuel_price.providers")
prov.__path__ = [str(COMP / "providers")]
sys.modules["custom_components.smart_fuel_price.providers"] = prov
import importlib.util

for _name in ["const", "config_flow"]:
    _spec = importlib.util.spec_from_file_location(
        f"custom_components.smart_fuel_price.{_name}", COMP / f"{_name}.py"
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"custom_components.smart_fuel_price.{_name}"] = _mod
    _spec.loader.exec_module(_mod)

cf = sys.modules["custom_components.smart_fuel_price.config_flow"]


@pytest.fixture(autouse=True)
def _clean_store():
    Store._db.clear()
    yield
    Store._db.clear()


class FakeHass:
    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def _cities(provider_key, monkey=None):
    async def go():
        return await cf._get_cities_for_provider(FakeHass(), provider_key)

    return asyncio.run(go())


def test_discovery_exception_falls_back_to_static():
    cls = cf._PROVIDER_CLASSES["citynews_ca"]
    with patch.object(
        cls, "discover_cities", classmethod(lambda c: (_ for _ in ()).throw(RuntimeError("boom")))
    ):
        cities = _cities("citynews_ca")
    assert cities == cls.get_supported_cities()
    assert "calgary" in cities


def test_filter_exception_falls_back_to_static():
    cls = cf._PROVIDER_CLASSES["citynews_ca"]
    with patch.object(
        cls, "discover_cities", classmethod(lambda c: {"toronto": "Toronto"})
    ), patch(
        "custom_components.smart_fuel_price.config_flow.filter_cities_with_prices",
        side_effect=RuntimeError("filter boom"),
    ):
        cities = _cities("citynews_ca")
    assert cities == cls.get_supported_cities()


def test_store_failure_falls_back_to_static(caplog):
    cls = cf._PROVIDER_CLASSES["affordableenergy_ca"]

    class BrokenStore(Store):
        async def async_load(self):
            raise OSError("disk gone")

    with patch(
        "custom_components.smart_fuel_price.config_flow.Store", BrokenStore
    ), caplog.at_level(logging.ERROR, logger="custom_components.smart_fuel_price.config_flow"):
        cities = _cities("affordableenergy_ca")
    assert cities == cls.get_supported_cities()
    assert "falling back" in caplog.text


def test_happy_path_still_discovers_and_filters():
    cls = cf._PROVIDER_CLASSES["citynews_ca"]
    with patch.object(
        cls, "discover_cities", classmethod(lambda c: {"toronto": "T", "edmonton": "E"})
    ), patch.object(cls, "city_has_prices", classmethod(lambda c, city, session=None: city != "edmonton")):
        cities = _cities("citynews_ca")
    assert cities == ["toronto"]


def test_store_version_mismatch_refreshes_instead_of_erroring(caplog):
    """HA's Store raises NotImplementedError when the stored cache was
    written by an older version (no migration function given). That must
    be treated as a cache miss -- refresh and re-save -- not an error
    that kills discovery on every config-flow open."""
    cls = cf._PROVIDER_CLASSES["affordableenergy_ca"]

    class MigratingStore(Store):
        async def async_load(self):
            raise NotImplementedError

    with patch(
        "custom_components.smart_fuel_price.config_flow.Store", MigratingStore
    ), patch.object(
        cls, "discover_cities", classmethod(lambda c: {"toronto": "T"})
    ), patch.object(
        cls, "city_has_prices", classmethod(lambda c, city, session=None: True)
    ), caplog.at_level(logging.INFO, logger="custom_components.smart_fuel_price.config_flow"):
        cities = _cities("affordableenergy_ca")
    assert cities == ["toronto"]
    assert "falling back" not in caplog.text
    # Self-healed: the refreshed cache was saved under the current version.
    assert MigratingStore._db[(cf._CITY_CACHE_VERSION, cf._CITY_CACHE_KEY)]["affordableenergy_ca"]["cities"] == ["toronto"]


def test_sitemap_removal_warns(caplog):
    cls = cf._PROVIDER_CLASSES["affordableenergy_ca"]
    with patch.object(
        cls, "discover_cities", classmethod(lambda c: {"toronto": "Toronto"})
    ), caplog.at_level(
        logging.WARNING, logger="custom_components.smart_fuel_price.config_flow"
    ):
        cities = _cities("affordableenergy_ca")
    assert cities == ["toronto"]
    assert "no longer in the discovery source" in caplog.text
    assert "vancouver-gas-prices" in caplog.text


def test_sitemap_no_removal_no_warning(caplog):
    cls = cf._PROVIDER_CLASSES["affordableenergy_ca"]
    discovered = {s: s for s in cls.verified_cities()} | {"burnaby": "Burnaby"}
    with patch.object(
        cls, "discover_cities", classmethod(lambda c: discovered)
    ), patch.object(
        cls,
        "city_has_prices",
        classmethod(lambda c, city, session=None: False),
    ), caplog.at_level(
        logging.WARNING, logger="custom_components.smart_fuel_price.config_flow"
    ):
        cities = _cities("affordableenergy_ca")
    # burnaby probed (unverified) and dropped; verified kept; no warning.
    assert set(cities) == set(cls.verified_cities())
    assert "no longer in the discovery source" not in caplog.text
