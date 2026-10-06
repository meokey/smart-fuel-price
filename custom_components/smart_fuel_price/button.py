"""Button platform for Smart Fuel Price: manual refresh per device."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Create one 'Refresh data' button per device of this config entry.

    The sensor platform registers its devices in
    ``hass.data[DOMAIN]["sensors"][entry_id]`` as
    ``{device_key: {"name": ..., "sensors": [...]}}``.
    """
    by_device = hass.data[DOMAIN].get("sensors", {}).get(config_entry.entry_id, {})
    buttons = [
        SmartFuelRefreshButton(device_key, info["name"], info["sensors"])
        for device_key, info in by_device.items()
    ]
    if not buttons:
        _LOGGER.debug("No Smart Fuel Price devices found for refresh buttons")
    async_add_entities(buttons)


class SmartFuelRefreshButton(ButtonEntity):
    """Force a fresh fetch for every sensor on this device, bypassing the
    TTL cache, and refresh the persisted cache with the new data."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:refresh"

    def __init__(self, device_key: str, device_name: str, sensors: list) -> None:
        self._sensors = sensors
        self._attr_name = "Refresh data"
        self._attr_unique_id = f"smart_fuel_price_{device_key}_refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_key)},
            name=device_name,
        )

    async def async_press(self) -> None:
        """Fetch fresh data for each sensor on this device."""
        for sensor in self._sensors:
            await sensor.async_force_refresh()
