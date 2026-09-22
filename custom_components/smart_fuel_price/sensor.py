"""Sensor platform for Smart Fuel Price (Config Flow enabled)."""
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import CONF_NAME
from homeassistant.util import Throttle

from .const import DOMAIN, CONF_PROVIDER, CONF_CITY, CONF_API_KEY, CONF_DISABLED_ATTRIBUTES
from .providers.affordableenergy_ca import AffordableEnergyCaProvider
from .providers.fuelwise_app import FuelwiseAppProvider
from .providers.globalpetrolprices import GlobalPetrolPricesProvider
from .providers.citynews_ca import CityNewsCaProvider

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(hours=4)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Smart Fuel Price sensor from a config entry."""
    data = config_entry.data
    options = config_entry.options

    # Retrieve settings
    name = data.get(CONF_NAME, config_entry.title)
    provider_type = data.get(CONF_PROVIDER).lower()
    city = data.get(CONF_CITY).lower()
    api_key = data.get(CONF_API_KEY, "")
    
    # Read disabled attributes dynamically
    disabled_attrs = options.get(CONF_DISABLED_ATTRIBUTES, data.get(CONF_DISABLED_ATTRIBUTES, []))

    # Initialize Provider
    if provider_type == "fuelwise_app":
        provider = FuelwiseAppProvider(city)
    elif provider_type == "globalpetrolprices":
        provider = GlobalPetrolPricesProvider(api_key, city)
    elif provider_type == "citynews_ca":
        provider = CityNewsCaProvider(city)
    else:
        provider = AffordableEnergyCaProvider(city)

    sensor = SmartFuelSensor(name, provider, disabled_attrs, config_entry.entry_id)
    async_add_entities([sensor], True)


class SmartFuelSensor(SensorEntity):
    """Representation of a Smart Fuel Price Sensor."""

    # Modern HA naming and statistics standards
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, name, provider, disabled_attributes, entry_id):
        self._provider = provider
        self._disabled_attributes = disabled_attributes
        
        # Entity settings
        self._attr_name = "Price Change"
        self._attr_native_unit_of_measurement = "¢/L"
        self._attr_icon = "mdi:gas-station"
        self._attr_unique_id = f"smart_fuel_price_{entry_id}"
        
        # Device Registry integration (Groups entity perfectly in UI)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=name,
            manufacturer=self._provider.name,
            model=f"{self._provider.city.capitalize()} Fuel Data",
        )
        
        self._state = None
        self._attributes = {}

    @property
    def native_value(self):
        """Return the actual state (price change)."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Dynamically filter out attributes disabled by user."""
        return {
            k: v for k, v in self._attributes.items() 
            if k not in self._disabled_attributes
        }

    @Throttle(SCAN_INTERVAL)
    async def async_update(self):
        """Defensive async update to fetch data without blocking the event loop."""
        try:
            _LOGGER.debug("Updating fuel price sensor via %s for city %s", self._provider.name, self._provider.city)
            
            # Delegate blocking synchronous API calls to the thread pool executor
            data = await self.hass.async_add_executor_job(self._provider.fetch_data)
            
            if data:
                self._state = data.get("state")
                self._attributes = data
            else:
                _LOGGER.warning("Received empty data payload from provider: %s", self._provider.name)
                
        except Exception as err:
            # Fail-safe mechanism: catch all exceptions to prevent automation/UI crashes
            _LOGGER.error("Error fetching data from %s: %s", self._provider.name, err)
            # Retain the previous known state rather than dropping to 'unavailable'
            self._attributes["is_valid"] = False
