"""Config flow for Smart Fuel Price supporting dynamic cities and multi-instance."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
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

from .providers.affordableenergy_ca import AffordableEnergyCaProvider
from .providers.fuelwise_app import FuelwiseAppProvider
from .providers.citynews_ca import CityNewsCaProvider
from .providers.globalpetrolprices import GlobalPetrolPricesProvider

_LOGGER = logging.getLogger(__name__)

def get_cities_for_provider(provider_key: str) -> list[str]:
    """Dynamically retrieve supported cities for a given provider."""
    provider_key = provider_key.lower()
    if provider_key == "citynews_ca":
        return CityNewsCaProvider.get_supported_cities()
    elif provider_key == "fuelwise_app":
        return FuelwiseAppProvider.get_supported_cities()
    elif provider_type == "globalpetrolprices":
        return GlobalPetrolPricesProvider.get_supported_cities()
    else:
        return AffordableEnergyCaProvider.get_supported_cities()


class SmartFuelPriceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Config Flow allowing multiple sensor instances."""

    VERSION = 1

    def __init__(self):
        """Initialize flow state."""
        self._selected_provider = "affordableenergy_ca"

    async def async_step_import(self, user_input=None):
        """Handle legacy configuration.yaml migration."""
        provider = user_input.get(CONF_PROVIDER, "affordableenergy_ca").lower()
        city = user_input.get(CONF_CITY, "mississauga").lower()
        
        unique_id = f"{provider}_{city}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"{AVAILABLE_PROVIDERS.get(provider, provider)} ({city.capitalize()})",
            data=user_input
        )

    async def async_step_user(self, user_input=None):
        """Handle step 1: Choose Provider and City."""
        errors = {}

        if user_input is not None:
            provider_key = user_input[CONF_PROVIDER].lower()
            city = user_input[CONF_CITY].lower()
            api_key = user_input.get(CONF_API_KEY, "").strip()

            # 验证 API Key
            if provider_key == "globalpetrolprices" and not api_key:
                errors["base"] = "invalid_api_key"

            # 验证城市合法性
            supported_cities = get_cities_for_provider(provider_key)
            if city not in supported_cities and supported_cities:
                errors["base"] = "unsupported_city"

            if not errors:
                # 唯一 ID 允许配置多个不同的 Provider 或不同的 City
                unique_id = f"{provider_key}_{city}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title_name = f"{AVAILABLE_PROVIDERS.get(provider_key, provider_key)} - {city.capitalize()}"
                return self.async_create_entry(
                    title=title_name,
                    data={
                        CONF_PROVIDER: provider_key,
                        CONF_CITY: city,
                        CONF_API_KEY: api_key,
                    }
                )

        # 默认城市推导 (根据 HA 坐标)
        default_city = "mississauga"
        supported_cities = get_cities_for_provider(self._selected_provider)
        if default_city not in supported_cities and supported_cities:
            default_city = supported_cities[0]

        schema = vol.Schema({
            vol.Required(CONF_PROVIDER, default="affordableenergy_ca"): vol.In(AVAILABLE_PROVIDERS),
            vol.Required(CONF_CITY, default=default_city): vol.In(supported_cities),
            vol.Optional(CONF_API_KEY, default=""): str,
        })

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Enable Options Flow for attribute management."""
        return SmartFuelPriceOptionsFlowHandler(config_entry)


class SmartFuelPriceOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Options Flow for toggling sensor attributes."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage attributes to disable."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_disabled = self.config_entry.options.get(
            CONF_DISABLED_ATTRIBUTES, 
            self.config_entry.data.get(CONF_DISABLED_ATTRIBUTES, [])
        )

        schema = vol.Schema({
            vol.Optional(
                CONF_DISABLED_ATTRIBUTES,
                default=current_disabled
            ): cv.multi_select(OPTIONAL_ATTRIBUTES)
        })

        return self.async_show_form(step_id="init", data_schema=schema)
