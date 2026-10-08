"""Sensor platform for Smart Fuel Price (Config Flow enabled)."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.const import CONF_NAME

from .const import (
    DOMAIN,
    CONF_PROVIDER,
    CONF_CITY,
    CONF_STATION_IDS,
    CONF_FUEL_GRADES,
    CONF_DISABLED_ATTRIBUTES,
    CONF_CACHE_TTL_MINUTES,
    DEFAULT_CACHE_TTL_MINUTES,
)
from .providers.base import fresh_cache_slot, merge_fetch_cache_slots, summarize_fetch_status

# Device "model" shown on the HA device info card: what KIND of data this
# device carries, at a glance (station live price vs city forecast).
_DEVICE_MODEL = {
    "gasbuddy_ca": "Gas station",
    "affordableenergy_ca": "City fuel forecast",
    "citynews_ca": "City fuel price",
}
from .providers.affordableenergy_ca import AffordableEnergyCaProvider
from .providers.citynews_ca import CityNewsCaProvider
from .providers.gasbuddy_ca import GasBuddyStationProvider

_LOGGER = logging.getLogger(__name__)
# Underlying HA poll trigger -- the provider's TTL cache (editable in the
# Options flow) decides whether a poll actually hits the network.
SCAN_INTERVAL = timedelta(minutes=15)

# Bumped to 2 in v2.3.24: GasBuddy values cached under v2.3.20/v2.3.21 were
# dollar-normalized (Amount/100) and would otherwise display mislabeled under
# the corrected \u00a2/L unit (e.g. a stale "1.749 \u00a2/L"). Old slots are
# dropped; every provider simply refetches on the next setup.
_FETCH_CACHE_VERSION = 2
_FETCH_CACHE_KEY = f"{DOMAIN}_fetch_cache"


def _cache_lock(hass) -> asyncio.Lock:
    """Process-wide lock serializing fetch-cache storage access.

    Every config entry loads the cache once at setup, then saves its own
    snapshot on its own poll schedule. Without serialization, the
    load-merge-save in _save_fetch_cache could interleave across entries.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    lock = domain_data.get("fetch_cache_lock")
    if lock is None:
        lock = asyncio.Lock()
        domain_data["fetch_cache_lock"] = lock
    return lock


async def _load_fetch_cache(hass) -> dict:
    """Load the persisted fetch cache ({cache_key: {data, fetched_at}})."""
    try:
        async with _cache_lock(hass):
            return await Store(hass, _FETCH_CACHE_VERSION, _FETCH_CACHE_KEY).async_load() or {}
    except Exception as err:  # noqa: BLE001 -- cache is best-effort
        _LOGGER.debug("Could not load fetch cache: %s", err)
        return {}


async def _save_fetch_cache(hass, fetch_cache: dict) -> None:
    """Persist the fetch cache, merging into what's already on disk.

    Best-effort -- never breaks updates. The merge (not a full overwrite)
    is what makes this safe across config entries: each entry only ever
    adds/refreshes its own providers' slots, so a save can never delete
    another entry's slots (see merge_fetch_cache_slots).
    """
    try:
        async with _cache_lock(hass):
            store = Store(hass, _FETCH_CACHE_VERSION, _FETCH_CACHE_KEY)
            current = await store.async_load() or {}
            await store.async_save(merge_fetch_cache_slots(current, fetch_cache))
    except Exception as err:  # noqa: BLE001 -- cache is best-effort
        # Warning, not debug: a persist failure is silent data loss -- the
        # cache won't survive the next restart, and nothing else signals it.
        _LOGGER.warning("Could not persist fetch cache: %s", err)


def _hydrate_provider(provider, fetch_cache: dict) -> None:
    """Restore a provider's in-memory cache from the persisted store."""
    slot = fetch_cache.get(provider.cache_key)
    if not slot or not slot.get("data"):
        _LOGGER.debug(
            "No persisted fetch-cache slot for %s; starting cold", provider.cache_key
        )
        return
    try:
        fetched_at = datetime.fromtimestamp(slot["fetched_at"], tz=timezone.utc)
        provider.hydrate_cache(slot["data"], fetched_at)
        _LOGGER.info(
            "Restored fetch cache for %s (data from %s)",
            provider.cache_key, fetched_at.isoformat(),
        )
    except Exception as err:  # noqa: BLE001 -- corrupt slot, just skip it
        _LOGGER.debug("Ignoring corrupt fetch-cache slot %s: %s", provider.cache_key, err)


def _ttl_for_entry(data, options, provider_type: str) -> timedelta:
    minutes = options.get(
        CONF_CACHE_TTL_MINUTES,
        data.get(CONF_CACHE_TTL_MINUTES, DEFAULT_CACHE_TTL_MINUTES.get(provider_type, 60)),
    )
    return timedelta(minutes=minutes)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Smart Fuel Price sensor(s) from a config entry."""
    data = config_entry.data
    options = config_entry.options

    name = data.get(CONF_NAME, config_entry.title)
    provider_key = data.get(CONF_PROVIDER)
    if not provider_key:
        _LOGGER.error(
            "Config entry %s has no provider configured; skipping setup",
            config_entry.entry_id,
        )
        return
    provider_type = provider_key.lower()
    disabled_attrs = options.get(CONF_DISABLED_ATTRIBUTES, data.get(CONF_DISABLED_ATTRIBUTES, []))
    ttl = _ttl_for_entry(data, options, provider_type)

    # Shared per-entry fetch cache ({cache_key: {data, fetched_at}}),
    # hydrated from .storage so sensors have data right after a restart.
    fetch_cache = await _load_fetch_cache(hass)
    hass.data[DOMAIN].setdefault("fetch_cache", {})[config_entry.entry_id] = fetch_cache

    # {device_key: {"name": ..., "sensors": [...]}} -- consumed by button.py
    # to build one manual-refresh button per device.
    by_device: dict = {}

    def _register(device_key: str, device_name: str, sensor: "SmartFuelSensor",
                provider) -> None:
        info = by_device.setdefault(
            device_key, {"name": device_name, "sensors": [], "providers": []}
        )
        info["sensors"].append(sensor)
        if provider not in info["providers"]:
            info["providers"].append(provider)

    if provider_type == "gasbuddy_ca":
        station_ids = [s.strip() for s in data.get(CONF_STATION_IDS, "").split(",") if s.strip()]
        fuel_grades = data.get(CONF_FUEL_GRADES, ["regular"])

        entities = []
        for station_id in station_ids:
            device_key = f"{config_entry.entry_id}_{station_id}"
            device_city = None
            device_station_name = None
            station_providers = []
            for grade in fuel_grades:
                provider = GasBuddyStationProvider(station_id, grade)
                provider.cache_ttl = ttl
                _hydrate_provider(provider, fetch_cache)
                station_providers.append(provider)
                # get_data() (not fetch_data()) so this warms the cache --
                # the first scheduled update then reuses it instead of
                # fetching twice.
                preview = await hass.async_add_executor_job(provider.get_data)
                # The preview may have hit the network (TTL expired) -- if so,
                # persist it like a regular update; otherwise a restart would
                # hydrate an older "Last updated" than the data we actually hold.
                slot = fresh_cache_slot(provider, preview)
                if slot is not None:
                    fetch_cache[provider.cache_key] = slot
                    await _save_fetch_cache(hass, fetch_cache)
                if device_city is None:
                    device_city = preview.get("city") or station_id
                    device_station_name = preview.get("station_name") or f"Station {station_id}"

                device_name = (
                    f"Smart Fuel Price - {device_city} - GasBuddy ({device_station_name})"
                )
                sensor = SmartFuelSensor(
                    device_name,
                    provider,
                    disabled_attrs,
                    device_key,
                    fetch_cache,
                    unique_suffix=grade,
                    suggested_area=device_city,
                    model=_DEVICE_MODEL["gasbuddy_ca"],
                    configuration_url=provider.source_url,
                )
                entities.append(sensor)
                _register(device_key, device_name, sensor, provider)
            device_model = _DEVICE_MODEL["gasbuddy_ca"]
            device_source_url = station_providers[0].source_url
            last_updated = SmartFuelLastUpdatedSensor(
                device_name, station_providers, "GasBuddy", device_key,
                suggested_area=device_city,
                model=device_model, configuration_url=device_source_url,
            )
            entities.append(last_updated)
            by_device[device_key]["last_updated"] = last_updated
            update_status = SmartFuelUpdateStatusSensor(
                device_name, station_providers, "GasBuddy", device_key,
                suggested_area=device_city,
                model=device_model, configuration_url=device_source_url,
            )
            entities.append(update_status)
            by_device[device_key]["update_status"] = update_status
            by_device[device_key]["model"] = device_model
            by_device[device_key]["configuration_url"] = device_source_url
        async_add_entities(entities, True)
        hass.data[DOMAIN].setdefault("sensors", {})[config_entry.entry_id] = by_device
        return

    city = data.get(CONF_CITY)
    if not city:
        _LOGGER.error(
            "Config entry %s has no city configured; skipping setup",
            config_entry.entry_id,
        )
        return
    city = city.lower()

    if provider_type == "citynews_ca":
        provider = CityNewsCaProvider(city)
    elif provider_type == "affordableenergy_ca":
        provider = AffordableEnergyCaProvider(city)
    else:
        # No silent fallback: an unknown (or removed, e.g. fuelwise_app)
        # provider string must fail loudly, not masquerade as Gas Wizard.
        _LOGGER.error(
            "Config entry %s uses unknown provider '%s'; skipping setup",
            config_entry.entry_id,
            provider_key,
        )
        return
    provider.cache_ttl = ttl
    _hydrate_provider(provider, fetch_cache)

    # (entity name, payload key, unique-id suffix). Price Change keeps the
    # historic unique_id so existing dashboards/automations don't break.
    if provider_type == "affordableenergy_ca":
        specs = [
            (None, "state", None),  # "Price Change" (legacy)
            ("Today's Price", "current_price", "today"),
            ("Tomorrow's Forecast", "tomorrow_price", "tomorrow"),
        ]
    else:
        specs = [(None, "state", None)]

    device_model = _DEVICE_MODEL.get(provider_type, "Fuel data")
    device_source_url = provider.source_url
    sensors = []
    for entity_name, value_key, suffix in specs:
        sensor = SmartFuelSensor(
            name, provider, disabled_attrs, config_entry.entry_id, fetch_cache,
            suggested_area=city.capitalize(),
            unique_suffix=suffix,
            entity_name=entity_name,
            value_key=value_key,
            model=device_model,
            configuration_url=device_source_url,
        )
        sensors.append(sensor)
        _register(config_entry.entry_id, name, sensor, provider)
    last_updated = SmartFuelLastUpdatedSensor(
        name, [provider], provider.name, config_entry.entry_id,
        suggested_area=city.capitalize(),
        model=device_model, configuration_url=device_source_url,
    )
    sensors.append(last_updated)
    by_device[config_entry.entry_id]["last_updated"] = last_updated
    update_status = SmartFuelUpdateStatusSensor(
        name, [provider], provider.name, config_entry.entry_id,
        suggested_area=city.capitalize(),
        model=device_model, configuration_url=device_source_url,
    )
    sensors.append(update_status)
    by_device[config_entry.entry_id]["update_status"] = update_status
    by_device[config_entry.entry_id]["model"] = device_model
    by_device[config_entry.entry_id]["configuration_url"] = device_source_url
    async_add_entities(sensors, True)
    hass.data[DOMAIN].setdefault("sensors", {})[config_entry.entry_id] = by_device


class SmartFuelLastUpdatedSensor(SensorEntity):
    """Per-device timestamp of the last successful data fetch.

    Covers both automatic polls and manual Refresh-button presses, so the
    device page always shows when its data was actually refreshed from the
    source. (The button entity's own timestamp only records manual presses
    -- standard HA button behavior -- which is why it can read "Unknown"
    or look stale next to fresh sensor data.)
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, device_name, providers, provider_name, device_key,
                 suggested_area=None, model=None, configuration_url=None):
        self._providers = list(providers)
        self._attr_name = "Last updated"
        self._attr_unique_id = f"smart_fuel_price_{device_key}_last_updated"
        # HA convention: credit the data source on every entity.
        self._attr_attribution = f"Data provided by {provider_name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_key)},
            name=device_name,
            manufacturer=provider_name,
            model=model,
            suggested_area=suggested_area,
            configuration_url=configuration_url,
        )

    @property
    def native_value(self):
        """Latest successful fetch across this device's providers.

        Computed live, not snapshotted in async_update: at setup the
        platforms' first updates can complete in any order, and a slow
        provider's fetch may not have landed when this sensor first
        updates -- reading the stamps live means the value is correct as
        soon as any fetch succeeds, instead of being stuck at Unknown.
        """
        stamps = [
            p.last_successful_fetch for p in self._providers
            if p.last_successful_fetch is not None
        ]
        return max(stamps) if stamps else None

    async def async_update(self):
        """No I/O -- the value is read live from the providers (see
        native_value). The providers themselves are polled through the
        regular price sensors on the same SCAN_INTERVAL."""


class SmartFuelUpdateStatusSensor(SensorEntity):
    """Per-device status of the last fetch attempt.

    States: "OK" (last attempt succeeded), "Rate limited" (the source
    answered HTTP 429, or 403 where it uses that for bot-protection),
    "Failed" (any other error). Unknown until the first attempt. Sits right
    next to the "Last updated" sensor; when automatic polls get
    rate-limited, a ``suggestion`` attribute advises raising the cache
    threshold in Options. (A manual press that hits the limit needs no such
    hint -- the user chose the timing.)
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["OK", "Rate limited", "Failed"]

    _DISPLAY = {"ok": "OK", "rate_limited": "Rate limited", "error": "Failed"}
    _ICONS = {
        "OK": "mdi:check-circle-outline",
        "Rate limited": "mdi:timer-sand",
        "Failed": "mdi:alert-circle-outline",
    }

    def __init__(self, device_name, providers, provider_name, device_key,
                 suggested_area=None, model=None, configuration_url=None):
        self._providers = list(providers)
        self._attr_name = "Update status"
        self._attr_unique_id = f"smart_fuel_price_{device_key}_update_status"
        # HA convention: credit the data source on every entity.
        self._attr_attribution = f"Data provided by {provider_name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_key)},
            name=device_name,
            manufacturer=provider_name,
            model=model,
            suggested_area=suggested_area,
            configuration_url=configuration_url,
        )

    @property
    def native_value(self):
        """Worst-of status across this device's providers, as display text."""
        summary = summarize_fetch_status(
            [p.last_fetch_status for p in self._providers]
        )
        return self._DISPLAY.get(summary)

    @property
    def icon(self):
        """Icon follows the status so the card reads at a glance."""
        return self._ICONS.get(self.native_value, "mdi:help-circle-outline")

    @property
    def extra_state_attributes(self):
        """Hint at raising the cache threshold when *automatic* polls are
        being rate-limited."""
        if any(
            p.last_fetch_status == "rate_limited" and not p.last_fetch_was_forced
            for p in self._providers
        ):
            return {
                "suggestion": (
                    "Automatic updates are being rate-limited by the source. "
                    "Consider increasing the cache threshold for this entry "
                    "(Options) to reduce the request rate."
                )
            }
        return {}

    async def async_update(self):
        """No I/O -- the status is read live from the providers."""


class SmartFuelSensor(SensorEntity):
    """Representation of a Smart Fuel Price Sensor."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device_name, provider, disabled_attributes, device_key,
                 fetch_cache, unique_suffix=None, suggested_area=None,
                 entity_name=None, value_key="state", model=None,
                 configuration_url=None):
        self._provider = provider
        self._disabled_attributes = disabled_attributes
        self._fetch_cache = fetch_cache
        # Which key of the provider payload drives this entity's state.
        self._value_key = value_key

        self._attr_name = entity_name or self._provider.sensor_name
        self._attr_native_unit_of_measurement = self._provider.native_unit_of_measurement
        self._attr_icon = "mdi:gas-station"
        # HA convention: credit the data source on every entity.
        self._attr_attribution = f"Data provided by {self._provider.name}"
        self._attr_unique_id = (
            f"smart_fuel_price_{device_key}_{unique_suffix}"
            if unique_suffix else f"smart_fuel_price_{device_key}"
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_key)},
            name=device_name,
            manufacturer=self._provider.name,
            model=model,
            suggested_area=suggested_area,
            configuration_url=configuration_url,
        )

        self._state = None
        self._attributes = {}

    @property
    def native_value(self):
        """Return the actual state (price change, or current price for GasBuddy)."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Dynamically filter out attributes disabled by user."""
        return {
            k: v for k, v in self._attributes.items()
            if k not in self._disabled_attributes
        }

    async def async_update(self):
        """Periodic poll -- the provider's TTL cache decides whether the
        network is actually hit."""
        await self._async_fetch(force=False)

    async def async_force_refresh(self):
        """Manual refresh (button entity): bypass the cache and fetch now."""
        await self._async_fetch(force=True)

    async def _async_fetch(self, force: bool) -> None:
        try:
            _LOGGER.debug(
                "Updating fuel price sensor via %s for city %s (force=%s)",
                self._provider.name, self._provider.city, force,
            )
            data = await self.hass.async_add_executor_job(self._provider.get_data, force)

            if data:
                self._state = data.get(self._value_key)
                self._attributes = data
                slot = fresh_cache_slot(self._provider, data)
                if slot is not None:
                    self._fetch_cache[self._provider.cache_key] = slot
                    await _save_fetch_cache(self.hass, self._fetch_cache)
            else:
                _LOGGER.warning("Received empty data payload from provider: %s", self._provider.name)

        except Exception as err:
            _LOGGER.error("Error fetching data from %s: %s", self._provider.name, err)
            self._attributes["is_valid"] = False
