"""Button platform for Smart Fuel Price: manual refresh per device."""
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Anti-abuse (#55): after a press, the button goes unavailable for a
# short cooldown so a struggling source can't be hammered by repeated
# taps. Matches the 60s automatic-retry suppression in providers/base.py.
_BUTTON_COOLDOWN_SECONDS = 60


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
        self._cooldown_until: datetime | None = None
        self._cooldown_handle = None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._cancel_cooldown)

    def _cancel_cooldown(self) -> None:
        handle, self._cooldown_handle = self._cooldown_handle, None
        if handle is not None:
            try:
                handle()
            except Exception:  # noqa: BLE001 -- best-effort cancel
                pass

    @property
    def available(self) -> bool:
        """False during the post-press cooldown (HA greys the button out)."""
        return (
            self._cooldown_until is None
            or datetime.now(timezone.utc) >= self._cooldown_until
        )

    @property
    def extra_state_attributes(self):
        return {
            "next_available_at": (
                self._cooldown_until.isoformat() if self._cooldown_until else None
            )
        }

    async def async_press(self) -> None:
        """Fetch fresh data once per unique provider on this device,
        bypassing the TTL cache.

        Afterwards every sensor re-reads from the warmed cache so entities
        sharing one provider can't end up showing different fetches -- and
        a slow source is hit once, not once per sensor. (Seen live: 3
        sequential forced fetches, each hitting a 10s read timeout.)
        """
        if not self.available:
            _LOGGER.debug("Manual refresh pressed during cooldown; ignoring")
            return
        refreshed: set = set()
        for sensor in self._sensors:
            provider = sensor._provider
            if provider not in refreshed:
                refreshed.add(provider)
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
        # Cooldown: grey the button out briefly so the source can't be
        # hammered by repeated taps (#55).
        self._cancel_cooldown()
        self._cooldown_until = datetime.now(timezone.utc) + timedelta(
            seconds=_BUTTON_COOLDOWN_SECONDS
        )
        self.async_write_ha_state()

        async def _reenable(_now):
            self._cooldown_handle = None
            self._cooldown_until = None
            self.async_write_ha_state()

        self._cooldown_handle = async_call_later(
            self.hass, _BUTTON_COOLDOWN_SECONDS, _reenable
        )
