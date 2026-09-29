"""Config flow for Smart Fuel Price supporting dynamic cities and multi-instance."""

import logging
import time

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.storage import Store
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    DEFAULT_NAME,
    CONF_PROVIDER,
    CONF_CITY,
    CONF_API_KEY,
    CONF_STATION_IDS,
    CONF_DISABLED_ATTRIBUTES,
    AVAILABLE_PROVIDERS,
    OPTIONAL_ATTRIBUTES,
)
from .providers.affordableenergy_ca import AffordableEnergyCaProvider
from .providers.fuelwise_app import FuelwiseAppProvider
from .providers.citynews_ca import CityNewsCaProvider
from .providers.gasbuddy_ca import GasBuddyStationProvider

_LOGGER = logging.getLogger(__name__)

_PROVIDER_CLASSES = {
    "citynews_ca": CityNewsCaProvider,
    "fuelwise_app": FuelwiseAppProvider,
    "affordableenergy_ca": AffordableEnergyCaProvider,
    # gasbuddy_ca deliberately excluded: it's station-based, not
    # city-based, and has no get_supported_cities()/discover_cities().
}

_CITY_CACHE_VERSION = 1
_CITY_CACHE_KEY = f"{DOMAIN}_city_cache"
_CITY_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 1 week -- these lists barely change


async def _get_cities_for_provider(hass, provider_key: str) -> list[str]:
    """Return cities for a provider, refreshed at most weekly.

    Order of preference: fresh cache -> live discover_cities() -> static
    get_supported_cities(). Results are persisted via HA's Store helper
    so a normal restart doesn't re-trigger a live fetch.
    """
    provider_key = provider_key.lower()
    provider_cls = _PROVIDER_CLASSES.get(provider_key, AffordableEnergyCaProvider)

    store = Store(hass, _CITY_CACHE_VERSION, _CITY_CACHE_KEY)
    cache = await store.async_load() or {}
    entry = cache.get(provider_key)

    now = time.time()
    if entry and (now - entry["fetched_at"]) < _CITY_CACHE_TTL_SECONDS:
        return entry["cities"]

    # Cache missing or stale -- best-effort live refresh. discover_cities()
    # does a blocking network call, so it must run off the event loop.
    discovered = await hass.async_add_executor_job(provider_cls.discover_cities)
    cities = sorted(discovered.keys()) if discovered else provider_cls.get_supported_cities()

    if cities:
        cache[provider_key] = {"cities": cities, "fetched_at": now}
        await store.async_save(cache)

    return cities or provider_cls.get_supported_cities()


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
        """Handle step 1: Choose Provider and City (or Station IDs for GasBuddy)."""
        errors = {}

        if user_input is not None:
            provider_key = user_input[CONF_PROVIDER].lower()
            self._selected_provider = provider_key  # keep the redisplayed form in sync
            api_key = user_input.get(CONF_API_KEY, "").strip()

            if provider_key == "gasbuddy_ca":
                raw_ids = user_input.get(CONF_STATION_IDS, "")
                station_ids = [s.strip() for s in raw_ids.split(",") if s.strip()]
                if not station_ids:
                    errors["base"] = "station_ids_required"

                if not errors:
                    unique_id = f"gasbuddy_ca_{'_'.join(sorted(station_ids))}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"{AVAILABLE_PROVIDERS.get(provider_key, provider_key)} "
                              f"({len(station_ids)} station{'s' if len(station_ids) != 1 else ''})",
                        data={
                            CONF_PROVIDER: provider_key,
                            CONF_STATION_IDS: ", ".join(station_ids),
                        },
                    )
            else:
                city = user_input.get(CONF_CITY, "").lower()

                supported_cities = await _get_cities_for_provider(self.hass, provider_key)
                if city not in supported_cities and supported_cities:
                    errors["base"] = "unsupported_city"

                if not errors:
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

        # Build the (re)displayed form using the most recently selected provider.
        default_city = "mississauga"
        supported_cities = await _get_cities_for_provider(self.hass, self._selected_provider)
        if default_city not in supported_cities and supported_cities:
            default_city = supported_cities[0] if supported_cities else default_city

        schema_dict = {
            vol.Required(CONF_PROVIDER, default=self._selected_provider): vol.In(AVAILABLE_PROVIDERS),
        }
        if self._selected_provider == "gasbuddy_ca":
            schema_dict[vol.Required(CONF_STATION_IDS)] = str
        else:
            schema_dict[vol.Required(CONF_CITY, default=default_city)] = (
                vol.In(supported_cities) if supported_cities else str
            )
            schema_dict[vol.Optional(CONF_API_KEY, default="")] = str

        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(schema_dict), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Enable Options Flow for attribute management."""
        return SmartFuelPriceOptionsFlowHandler()


class SmartFuelPriceOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Options Flow for toggling sensor attributes."""

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
