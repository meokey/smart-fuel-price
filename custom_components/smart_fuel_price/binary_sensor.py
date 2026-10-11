"""Buy-now decision binary sensor for Smart Fuel Price.

Follows the device structure built by sensor.py (same pattern as button.py):
one binary sensor per device, reading the shared provider cache.

Decision rule (per device, first provider with a complete forecast wins):
- tomorrow_price is None or current_price is None -> unknown
  (e.g. GasBuddy pure current-price layout has no forecast)
- tomorrow_price > current_price -> on  ("fill up today")
- otherwise -> off ("wait for tomorrow")

The data-source reference is the config entry / device key, kept abstract
so future city-selector improvements (#54) can plug in without rework.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=15)


def _decide(providers) -> tuple[bool | None, float | None, dict[str, Any]]:
    """Return (buy_now, delta, details) for a device's providers.

    buy_now is None (unknown) when no provider has a complete forecast.
    delta is tomorrow_price - current_price in ¢/L.
    """
    for provider in providers:
        try:
            data = provider.get_data()
        except Exception:  # noqa: BLE001 -- never break the sensor on read
            _LOGGER.debug("buy-now: get_data failed", exc_info=True)
            continue
        tomorrow = data.get("tomorrow_price")
        today = data.get("current_price")
        if tomorrow is None or today is None:
            continue
        try:
            delta = float(tomorrow) - float(today)
        except (TypeError, ValueError):
            continue
        return (delta > 0), delta, {
            "tomorrow_price": tomorrow,
            "current_price": today,
        }
    return None, None, {}


class SmartFuelBuyNowSensor(BinarySensorEntity):
    """Binary sensor answering: should I fill up today?"""

    _attr_has_entity_name = True

    def __init__(
        self,
        device_name: str,
        providers,
        device_key: str,
        model: str | None = None,
        configuration_url: str | None = None,
    ) -> None:
        self._providers = providers
        self._attr_name = "Buy now"
        self._attr_unique_id = f"{device_key}_buy_now"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_key)},
            name=device_name,
            manufacturer="Smart Fuel Price",
            model=model or "Fuel data",
            configuration_url=configuration_url,
        )
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._buy_now: bool | None = None
        self._delta: float | None = None
        self._details: dict[str, Any] = {}

    @property
    def is_on(self) -> bool | None:
        return self._buy_now

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._delta is not None:
            attrs["price_delta"] = round(self._delta, 1)
        attrs.update(self._details)
        return attrs

    @property
    def icon(self) -> str:
        if self._buy_now is None:
            return "mdi:fuel"
        return "mdi:fuel" if self._buy_now else "mdi:timer-outline"

    async def async_update(self) -> None:
        """Derive the decision from the shared provider cache (executor)."""
        self._buy_now, self._delta, self._details = await self.hass.async_add_executor_job(
            _decide, self._providers
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one buy-now sensor per device from a config entry."""
    by_device = hass.data[DOMAIN].get("sensors", {}).get(config_entry.entry_id, {})
    entities: list[SmartFuelBuyNowSensor] = []
    for device_key, info in by_device.items():
        entities.append(
            SmartFuelBuyNowSensor(
                device_name=info["name"],
                providers=info.get("providers", []),
                device_key=device_key,
                model=info.get("model"),
                configuration_url=info.get("configuration_url"),
            )
        )
    async_add_entities(entities, True)
