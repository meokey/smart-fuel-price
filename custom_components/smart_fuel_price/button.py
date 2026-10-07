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
        SmartFuelRefreshButton(
            device_key, info["name"], info["sensors"],
            info.get("last_updated"), info.get("update_status"),
            model=info.get("model"), configuration_url=info.get("configuration_url"),
        )
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

    def __init__(self, device_key: str, device_name: str, sensors: list,
                 last_updated=None, update_status=None, model=None,
                 configuration_url=None) -> None:
        self._sensors = sensors
        self._last_updated = last_updated
        self._update_status = update_status
        self._attr_name = "Manual refresh"
        self._attr_unique_id = f"smart_fuel_price_{device_key}_refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_key)},
            name=device_name,
            model=model,
            configuration_url=configuration_url,
        )

    async def async_press(self) -> None:
        """Fetch fresh data for each sensor on this device.

        Afterwards every sensor re-reads from the warmed cache so entities
        sharing one provider can't end up showing different fetches.
        """
        for sensor in self._sensors:
            await sensor.async_force_refresh()
        for sensor in self._sensors:
            await sensor.async_update()
        # The manual fetch just ran -- reflect it on the device's
        # "Last updated" / "Update status" sensors immediately instead of
        # waiting for the next poll.
        for entity in (self._last_updated, self._update_status):
            if entity is not None:
                await entity.async_update()
                entity.async_write_ha_state()
