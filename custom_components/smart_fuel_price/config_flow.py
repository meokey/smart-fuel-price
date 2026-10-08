"""Config flow for Smart Fuel Price supporting dynamic cities and multi-instance."""

import asyncio
import logging
import time

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_PROVIDER,
    CONF_CITY,
    CONF_STATION_IDS,
    CONF_FUEL_GRADES,
    CONF_DISABLED_ATTRIBUTES,
    CONF_CACHE_TTL_MINUTES,
    DEFAULT_CACHE_TTL_MINUTES,
    AVAILABLE_PROVIDERS,
    GASBUDDY_FUEL_GRADES,
    OPTIONAL_ATTRIBUTES,
)
from .providers.affordableenergy_ca import AffordableEnergyCaProvider
from .providers.citynews_ca import CityNewsCaProvider
from .providers.gasbuddy_ca import GasBuddyStationProvider

_LOGGER = logging.getLogger(__name__)

_PROVIDER_CLASSES = {
    "citynews_ca": CityNewsCaProvider,
    "affordableenergy_ca": AffordableEnergyCaProvider,
    # gasbuddy_ca deliberately excluded: it's station-based, not
    # city-based, and has no get_supported_cities()/discover_cities().
}

_CITY_CACHE_VERSION = 1
_CITY_CACHE_KEY = f"{DOMAIN}_city_cache"
_CITY_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 1 week -- these lists barely change


async def _get_cities_for_provider(hass, provider_key: str) -> list[str]:
    """Return cities for a provider, refreshed at most weekly."""
    provider_key = provider_key.lower()
    provider_cls = _PROVIDER_CLASSES.get(provider_key, AffordableEnergyCaProvider)

    store = Store(hass, _CITY_CACHE_VERSION, _CITY_CACHE_KEY)
    cache = await store.async_load() or {}
    entry = cache.get(provider_key)

    now = time.time()
    if entry and (now - entry["fetched_at"]) < _CITY_CACHE_TTL_SECONDS:
        return entry["cities"]

    discovered = await hass.async_add_executor_job(provider_cls.discover_cities)
    cities = sorted(discovered.keys()) if discovered else provider_cls.get_supported_cities()

    if cities:
        cache[provider_key] = {"cities": cities, "fetched_at": now}
        await store.async_save(cache)

    return cities or provider_cls.get_supported_cities()


async def _validate_station(
    hass, station_id: str, fuel_grades: list[str]
) -> tuple[bool, list[str]]:
    """Validate a station ID plus every selected grade, with one request.

    Returns (station_valid, missing_grades) -- see
    GasBuddyStationProvider.check_station_grades.
    """
    provider = GasBuddyStationProvider(station_id, fuel_grades[0])
    return await hass.async_add_executor_job(provider.check_station_grades, fuel_grades)


class SmartFuelPriceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Config Flow allowing multiple sensor instances.

    Two-step flow: step "user" picks only the provider; step "details"
    then shows fields specific to that provider (city, or station IDs
    for GasBuddy). A single flat form can't do this -- HA doesn't
    re-render a form when one field changes, only when the whole form is
    submitted, so a single-step form always showed whatever was relevant
    to the *previous* selection, not the current one.
    """

    VERSION = 1

    def __init__(self):
        self._selected_provider = None

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
        """Step 1: choose the provider."""
        if user_input is not None:
            self._selected_provider = user_input[CONF_PROVIDER].lower()
            return await self.async_step_details()

        schema = vol.Schema({
            vol.Required(CONF_PROVIDER, default="affordableenergy_ca"): vol.In(AVAILABLE_PROVIDERS),
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_details(self, user_input=None):
        """Step 2: provider-specific fields (city, or station IDs for GasBuddy)."""
        errors = {}
        missing_grades = ""
        provider_key = self._selected_provider

        if user_input is not None:
            if provider_key == "gasbuddy_ca":
                raw_ids = user_input.get(CONF_STATION_IDS, "")
                station_ids = [s.strip() for s in raw_ids.split(",") if s.strip()]
                fuel_grades = user_input.get(CONF_FUEL_GRADES, [])

                if not station_ids:
                    errors["base"] = "station_ids_required"
                elif not fuel_grades:
                    errors["base"] = "fuel_grade_required"
                else:
                    # Validate every (station, grade) live so a typo is
                    # caught now, not silently at the first sensor poll.
                    # One request per station covers all its grades (the
                    # payload already contains every fuel the station
                    # offers).
                    results = await asyncio.gather(
                        *(_validate_station(self.hass, s, fuel_grades) for s in station_ids)
                    )
                    if not all(valid for valid, _ in results):
                        errors["base"] = "invalid_station_id"
                    else:
                        missing_grades = "; ".join(
                            f"{sid} ({', '.join(grades)})"
                            for sid, (_, grades) in zip(station_ids, results)
                            if grades
                        )
                        if missing_grades:
                            errors["base"] = "unsupported_fuel_grade"

                if not errors:
                    unique_id = f"gasbuddy_ca_{'_'.join(sorted(station_ids))}_{'_'.join(sorted(fuel_grades))}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Smart Fuel Price - GasBuddy "
                              f"({len(station_ids)} station{'s' if len(station_ids) != 1 else ''})",
                        data={
                            CONF_PROVIDER: provider_key,
                            CONF_STATION_IDS: ", ".join(station_ids),
                            CONF_FUEL_GRADES: fuel_grades,
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
                    return self.async_create_entry(
                        title=f"Smart Fuel Price - {city.capitalize()} - {AVAILABLE_PROVIDERS.get(provider_key, provider_key)}",
                        data={CONF_PROVIDER: provider_key, CONF_CITY: city},
                    )

        if provider_key == "gasbuddy_ca":
            schema = vol.Schema({
                vol.Required(CONF_STATION_IDS): str,
                vol.Required(CONF_FUEL_GRADES, default=["regular"]): cv.multi_select(GASBUDDY_FUEL_GRADES),
            })
        else:
            supported_cities = await _get_cities_for_provider(self.hass, provider_key)
            default_city = supported_cities[0] if supported_cities else "mississauga"
            schema = vol.Schema({
                vol.Required(CONF_CITY, default=default_city): (
                    vol.In(supported_cities) if supported_cities else str
                ),
            })

        return self.async_show_form(
            step_id="details",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "provider": AVAILABLE_PROVIDERS.get(provider_key, provider_key),
                "grades": missing_grades,
            },
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
        provider_key = (self.config_entry.data.get(CONF_PROVIDER) or "").lower()
        current_ttl = self.config_entry.options.get(
            CONF_CACHE_TTL_MINUTES,
            self.config_entry.data.get(
                CONF_CACHE_TTL_MINUTES,
                DEFAULT_CACHE_TTL_MINUTES.get(provider_key, 60),
            ),
        )
        schema = vol.Schema({
            vol.Optional(
                CONF_DISABLED_ATTRIBUTES,
                default=current_disabled
            ): cv.multi_select(OPTIONAL_ATTRIBUTES),
            vol.Optional(
                CONF_CACHE_TTL_MINUTES,
                default=current_ttl,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=1440, step=5, unit_of_measurement="min"
                )
            ),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
