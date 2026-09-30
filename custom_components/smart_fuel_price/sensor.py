"""Sensor platform for Smart Fuel Price (Config Flow enabled)."""
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import CONF_NAME
from homeassistant.util import dt as dt_util

from .const import DOMAIN, CONF_PROVIDER, CONF_CITY, CONF_STATION_IDS, CONF_FUEL_GRADES, CONF_DISABLED_ATTRIBUTES
from .providers.affordableenergy_ca import AffordableEnergyCaProvider
from .providers.fuelwise_app import FuelwiseAppProvider
from .providers.citynews_ca import CityNewsCaProvider
from .providers.gasbuddy_ca import GasBuddyStationProvider

_LOGGER = logging.getLogger(__name__)
# Underlying HA poll trigger -- short enough to satisfy the fastest
# provider (GasBuddy's 30 min). Slower providers simply no-op most of
# these calls via their own scan_interval (see SmartFuelSensor.async_update).
SCAN_INTERVAL = timedelta(minutes=15)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Smart Fuel Price sensor(s) from a config entry."""
    data = config_entry.data
    options = config_entry.options

    name = data.get(CONF_NAME, config_entry.title)
    provider_type = data.get(CONF_PROVIDER).lower()
    disabled_attrs = options.get(CONF_DISABLED_ATTRIBUTES, data.get(CONF_DISABLED_ATTRIBUTES, []))

    if provider_type == "gasbuddy_ca":
        station_ids = [s.strip() for s in data.get(CONF_STATION_IDS, "").split(",") if s.strip()]
        fuel_grades = data.get(CONF_FUEL_GRADES, ["regular"])

        entities = []
        for station_id in station_ids:
            device_key = f"{config_entry.entry_id}_{station_id}"
            device_city = None
            device_station_name = None
            for grade in fuel_grades:
                provider = GasBuddyStationProvider(station_id, grade)
                preview = await hass.async_add_executor_job(provider.fetch_data)
                if device_city is None:
                    device_city = preview.get("city") or station_id
                    device_station_name = preview.get("station_name") or f"Station {station_id}"

                entities.append(
                    SmartFuelSensor(
                        f"Smart Fuel Price - {device_city} - GasBuddy ({device_station_name})",
                        provider,
                        disabled_attrs,
                        device_key,
                        unique_suffix=grade,
                        suggested_area=device_city,
                    )
                )
        async_add_entities(entities, True)
        return

    city = data.get(CONF_CITY).lower()

    if provider_type == "fuelwise_app":
        provider = FuelwiseAppProvider(city)
    elif provider_type == "citynews_ca":
        provider = CityNewsCaProvider(city)
    else:
        provider = AffordableEnergyCaProvider(city)

    sensor = SmartFuelSensor(
        name, provider, disabled_attrs, config_entry.entry_id,
        suggested_area=city.capitalize(),
    )
    async_add_entities([sensor], True)


class SmartFuelSensor(SensorEntity):
    """Representation of a Smart Fuel Price Sensor."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device_name, provider, disabled_attributes, device_key, unique_suffix=None, suggested_area=None):
        self._provider = provider
        self._disabled_attributes = disabled_attributes
        self._last_fetch_time = None

        self._attr_name = self._provider.sensor_name
        self._attr_native_unit_of_measurement = self._provider.native_unit_of_measurement
        self._attr_icon = "mdi:gas-station"
        self._attr_unique_id = (
            f"smart_fuel_price_{device_key}_{unique_suffix}"
            if unique_suffix else f"smart_fuel_price_{device_key}"
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_key)},
            name=device_name,
            manufacturer=self._provider.name,
            model=f"{self._provider.city.capitalize()} Fuel Data",
            suggested_area=suggested_area,
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
        """Fetch data, throttled per-provider (see BaseFuelPriceProvider.scan_interval)."""
        now = dt_util.utcnow()
        if (
            self._last_fetch_time is not None
            and now - self._last_fetch_time < self._provider.scan_interval
        ):
            return  # Too soon for this provider -- keep the previous state.

        try:
            _LOGGER.debug("Updating fuel price sensor via %s for city %s", self._provider.name, self._provider.city)
            data = await self.hass.async_add_executor_job(self._provider.fetch_data)
            self._last_fetch_time = now

            if data:
                self._state = data.get("state")
                self._attributes = data
            else:
                _LOGGER.warning("Received empty data payload from provider: %s", self._provider.name)

        except Exception as err:
            _LOGGER.error("Error fetching data from %s: %s", self._provider.name, err)
            self._attributes["is_valid"] = False
