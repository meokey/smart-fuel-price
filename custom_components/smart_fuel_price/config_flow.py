"""Config flow for Smart Fuel Price."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN, 
    DEFAULT_NAME, 
    CONF_PROVIDER, 
    CONF_CITY, 
    CONF_API_KEY, 
    CONF_DISABLED_ATTRIBUTES,
    AVAILABLE_PROVIDERS,
    OPTIONAL_ATTRIBUTES
)

# Import providers to fetch real-time supported cities dynamically
from .providers.affordableenergy_ca import AffordableEnergyCaProvider
from .providers.fuelwise_app import FuelwiseAppProvider
from .providers.citynews_ca import CityNewsCaProvider
from .providers.globalpetrolprices import GlobalPetrolPricesProvider

_LOGGER = logging.getLogger(__name__)

class SmartFuelPriceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart Fuel Price."""

    VERSION = 1

    async def async_step_import(self, user_input=None):
        """Handle import from legacy configuration.yaml (Silent Upgrade)."""
        # Ensure we don't create duplicate entries for the same city+provider
        unique_id = f"{user_input.get(CONF_PROVIDER)}_{user_input.get(CONF_CITY)}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=user_input.get(CONF_NAME, DEFAULT_NAME), 
            data=user_input
        )

    async def async_step_user(self, user_input=None):
        """Handle the initial user setup via UI."""
        errors = {}

        if user_input is not None:
            provider_key = user_input[CONF_PROVIDER]
            city = user_input[CONF_CITY].lower()
            api_key = user_input.get(CONF_API_KEY, "")

            # Dynamically instantiate the provider to validate the city
            # This fulfills the requirement: check if city is valid for this provider
            if provider_key == "affordableenergy_ca":
                provider_test = AffordableEnergyCaProvider(city)
            elif provider_key == "fuelwise_app":
                provider_test = FuelwiseAppProvider(city)
            elif provider_key == "citynews_ca":
                provider_test = CityNewsCaProvider(city)
            elif provider_key == "globalpetrolprices":
                if not api_key:
                    errors["base"] = "invalid_api_key"
                provider_test = GlobalPetrolPricesProvider(api_key, city)
            else:
                errors["base"] = "unknown_provider"

            # Check if city is in the provider's supported list
            if not errors and city not in provider_test.get_supported_cities():
                errors["base"] = "unsupported_city"
                _LOGGER.error("City '%s' not supported by provider '%s'", city, provider_key)

            if not errors:
                # Validation passed. Set unique ID and create entry.
                unique_id = f"{provider_key}_{city}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=f"{AVAILABLE_PROVIDERS[provider_key]} - {city.capitalize()}", 
                    data=user_input
                )

        # Base schema preparation
        # Requirement: Use HA location to guess default city if possible
        default_city = "mississauga" # Default fallback
        if self.hass.config.latitude and self.hass.config.longitude:
            # (In a real advanced scenario, you'd calculate distance here. 
            # For now, we assume user is in GTA based on context)
            lat = self.hass.config.latitude
            if 43.0 < lat < 44.0:
                default_city = "mississauga"

        schema = vol.Schema({
            vol.Required(CONF_PROVIDER, default="affordableenergy_ca"): vol.In(AVAILABLE_PROVIDERS),
            vol.Required(CONF_CITY, default=default_city): str,
            vol.Optional(CONF_API_KEY, default=""): str,
        })

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return SmartFuelPriceOptionsFlowHandler(config_entry)


class SmartFuelPriceOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow (Configure button in UI)."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options (Disable specific attributes)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Read current disabled attributes from options
        current_disabled = self.config_entry.options.get(CONF_DISABLED_ATTRIBUTES, [])

        options_schema = vol.Schema({
            vol.Optional(
                CONF_DISABLED_ATTRIBUTES, 
                default=current_disabled
            ): cv.multi_select(OPTIONAL_ATTRIBUTES)
        })

        return self.async_show_form(
            step_id="init", 
            data_schema=options_schema,
            description_placeholders={"info": "Select attributes you want to HIDE."}
        )
