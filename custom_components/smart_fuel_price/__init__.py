"""
The Smart Fuel Price integration setup.
Handles transparent migration from YAML to Config Flow.
"""
import logging

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONF_PROVIDER, CONF_CITY, CONF_DISABLED_ATTRIBUTES

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

# Legacy YAML entries must be a list of dicts. Coerce a lone dict-style
# block into a single-entry list so async_setup's iteration below never
# yields bare dict keys (which would crash async_step_import on
# user_input.get).
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required(CONF_PROVIDER): str,
                        vol.Optional(CONF_CITY): str,
                    }
                )
            ],
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration and migrate legacy YAML configuration."""
    hass.data.setdefault(DOMAIN, {})

    if DOMAIN in config:
        # YAML configuration exists, initiate silent import to Config Flow
        _LOGGER.warning(
            "YAML configuration for smart_fuel_price is deprecated. "
            "Migrating to UI configuration automatically."
        )
        for entry in config[DOMAIN]:
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_IMPORT},
                    data=entry,
                )
            )
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Fuel Price from a config entry (UI)."""
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Forward the setup to each platform SEQUENTIALLY (not
    # async_forward_entry_setups, which fans out concurrently): the button
    # platform builds its entities from the device registry populated by
    # the sensor platform, so it must run strictly after the sensor setup
    # has completed. Concurrent setup raced and silently produced zero
    # buttons.
    for platform in PLATFORMS:
        await hass.config_entries.async_forward_entry_setup(entry, platform)

    # Register an update listener for Options Flow (when user changes settings)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Drop per-entry runtime state owned by the sensor/button platforms.
        hass.data[DOMAIN].get("sensors", {}).pop(entry.entry_id, None)
        hass.data[DOMAIN].get("fetch_cache", {}).pop(entry.entry_id, None)
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
