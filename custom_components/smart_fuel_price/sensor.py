"""
Sensor platform for Smart Fuel Price.
Supports multiple configurable providers, city routing, and attribute filtering.
"""
import logging
from datetime import timedelta
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv
from homeassistant.util import Throttle

from .providers.affordableenergy_ca import AffordableEnergyCaProvider
from .providers.fuelwise_app import FuelwiseAppProvider
from .providers.globalpetrolprices import GlobalPetrolPricesProvider
from .providers.citynews_ca import CityNewsCaProvider

_LOGGER = logging.getLogger(__name__)

DOMAIN = "smart_fuel_price"
DEFAULT_NAME = "Tomorrow Fuel Price Change"

CONF_PROVIDER = "provider"
CONF_CITY = "city"
CONF_API_KEY = "api_key"
CONF_DISABLED_ATTRIBUTES = "disabled_attributes"

SCAN_INTERVAL = timedelta(hours=4)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_PROVIDER, default="affordableenergy_ca"): cv.string,
    vol.Optional(CONF_CITY, default="mississauga"): cv.string,
    vol.Optional(CONF_API_KEY, default=""): cv.string,
    vol.Optional(CONF_DISABLED_ATTRIBUTES, default=[]): cv.ensure_list,
})

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Smart Fuel Price sensor platform."""
    name = config.get(CONF_NAME)
    provider_type = config.get(CONF_PROVIDER).lower()
    city = config.get(CONF_CITY).lower()
    api_key = config.get(CONF_API_KEY)
    disabled_attrs = config.get(CONF_DISABLED_ATTRIBUTES)

    # Provider Factory
    if provider_type == "fuelwise_app":
        provider = FuelwiseAppProvider(city)
    elif provider_type == "globalpetrolprices":
        provider = GlobalPetrolPricesProvider(api_key, city)
    elif provider_type == "citynews_ca": 
        provider = CityNewsCaProvider(city)
    else:
        provider = AffordableEnergyCaProvider(city)

    add_entities([SmartFuelSensor(name, provider, disabled_attrs)], True)

class SmartFuelSensor(SensorEntity):
    """Representation of a Smart Fuel Price Sensor."""

    def __init__(self, name, provider, disabled_attributes=None):
        self._attr_name = name
        self._provider = provider
        self._disabled_attributes = disabled_attributes or []
        self._attr_native_unit_of_measurement = "¢/L"
        self._attr_icon = "mdi:gas-station"
        self._state = None
        self._attributes = {}

    @property
    def native_value(self):
        # Return the actual state (price change).
        return self._state

    @property
    def extra_state_attributes(self):
        # Dynamically filter out attributes disabled by user in configuration
        return {
            k: v for k, v in self._attributes.items() 
            if k not in self._disabled_attributes
        }

    @Throttle(SCAN_INTERVAL)
    def update(self):
        """Fetch updated data from the designated provider."""
        _LOGGER.debug("Updating fuel price sensor using %s for city %s", self._provider.name, self._provider.city)
        data = self._provider.fetch_data()
        
        self._state = data.get("state")
        self._attributes = data
