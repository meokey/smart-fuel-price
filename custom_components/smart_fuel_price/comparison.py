"""Forecast-vs-NRC comparison readiness notifications (#85).

An integration cannot create dashboard cards: Lovelace dashboards are
user-owned configuration and Home Assistant exposes no integration-facing
API to add cards to them (writing .storage directly would be fragile,
break YAML-mode dashboards, and fight the frontend -- not done here).

What we *can* do is notice when a comparison becomes possible -- the NRC
weekly history is imported for a city AND a forecast provider (Gas Wizard
/ CityNews) tracks the same city -- and hand the user a persistent
notification with ready-to-paste statistics-graph YAML. One notification
per city; dismissing it never re-fires.
"""

import logging

from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_NOTIFY_STORE_VERSION = 1
_NOTIFY_STORE_KEY = f"{DOMAIN}_comparison_notify"

# Forecast providers whose sensors pair with the NRC weekly reference.
# Gas Wizard == AffordableEnergyCaProvider. Matched by class name so this
# module never imports provider implementations.
FORECAST_PROVIDER_CLASS_NAMES = frozenset(
    {
        "AffordableEnergyCaProvider",
        "CityNewsCaProvider",
    }
)

_VALUE_KEY_LABELS = {
    "current_price": "today",
    "tomorrow_price": "forecast",
    "state": "price",
}

# Step-by-step card guide (linked from the notification).
_DOCS_URL = (
    "https://github.com/meokey/smart-fuel-price/blob/main/docs/"
    "Dashboard-cards.md#4-forecast-vs-nrc-reference-history-graph"
)


async def _load_state(hass) -> dict:
    """Load (and memory-cache) the comparison notification state."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    state = domain_data.get("comparison_notify")
    if state is None:
        store = Store(hass, _NOTIFY_STORE_VERSION, _NOTIFY_STORE_KEY)
        state = await store.async_load() or {}
        domain_data["comparison_notify"] = state
    return state


async def _save_state(hass, state: dict) -> None:
    hass.data[DOMAIN]["comparison_notify"] = state
    await Store(hass, _NOTIFY_STORE_VERSION, _NOTIFY_STORE_KEY).async_save(
        state
    )


async def record_nrc_history_ready(hass, city: str, weeks: int) -> None:
    """Remember that the NRC backfill produced `weeks` of history for city."""
    if weeks <= 0:
        return
    state = await _load_state(hass)
    ready = state.setdefault("history_ready", {})
    if ready.get(city) != weeks:
        ready[city] = weeks
        await _save_state(hass, state)


def _forecast_sensors_for_city(hass, city: str) -> list:
    """Live forecast-provider sensors configured for `city`.

    Returns [(provider_name, entity_id, value_key), ...]. Sensors whose
    entity_id isn't assigned yet are skipped -- the check re-runs on
    every fetch until it succeeds, so nothing is lost.
    """
    found = []
    sensors_by_entry = hass.data.get(DOMAIN, {}).get("sensors", {})
    for by_device in sensors_by_entry.values():
        for info in by_device.values():
            for provider in info.get("providers", []):
                if (
                    type(provider).__name__ in FORECAST_PROVIDER_CLASS_NAMES
                    and getattr(provider, "city", None) == city
                ):
                    for sensor in info.get("sensors", []):
                        entity_id = getattr(sensor, "entity_id", None)
                        value_key = getattr(sensor, "_value_key", None)
                        if entity_id and value_key:
                            found.append(
                                (provider.name, entity_id, value_key)
                            )
    return found


def _comparison_yaml(city: str, forecast_entities: list) -> str:
    """statistics-graph YAML: forecast entities vs the NRC weekly average."""
    lines = [
        "type: statistics-graph",
        f"title: {city.capitalize()} - forecast vs NRC weekly average",
        "entities:",
        f"  - smart_fuel_price:nrc_weekly_{city}",
    ]
    for provider_name, entity_id, value_key in sorted(forecast_entities):
        label = _VALUE_KEY_LABELS.get(value_key, value_key)
        lines.append(f"  - entity: {entity_id}")
        lines.append(f"    name: {provider_name} ({label})")
    lines += [
        "stat_types:",
        "  - mean",
        "days_to_show: 365",
    ]
    return "\n".join(lines)


async def maybe_notify_comparison_ready(hass, city: str) -> bool:
    """Notify once per city when NRC history + forecast data coexist.

    Returns True when a notification was sent. Never raises: notification
    delivery must not break sensor updates.
    """
    try:
        state = await _load_state(hass)
        if city in state.get("notified", []):
            return False
        ready = state.get("history_ready", {})
        if city not in ready:
            return False
        forecast = _forecast_sensors_for_city(hass, city)
        if not forecast:
            return False

        names = sorted({name for name, _, _ in forecast})
        yaml_block = _comparison_yaml(city, forecast)
        message = (
            f"The NRC weekly price history for {city.capitalize()} "
            f"({ready[city]} weeks) is now in Home Assistant long-term "
            f"statistics, and {' and '.join(names)} also track this city.\n\n"
            "**Add the comparison card** (about 2 minutes):\n"
            "1. Open your dashboard, then the menu (top right) -> "
            "Edit dashboard -> Add card.\n"
            "2. Search for `Manual`, select it, and delete the placeholder "
            "text.\n"
            "3. Paste the YAML below, then Save. The card shows the "
            "forecast against the official weekly average.\n\n"
            f"```yaml\n{yaml_block}\n```\n\n"
            "Using the raw configuration editor instead? Paste the card as "
            "an item under a view's `cards:` list -- not at the end of the "
            "file. Indentation matters; a wrong indent is the most common "
            "error.\n\n"
            f"Step-by-step guide with pitfalls: [Dashboard cards]({_DOCS_URL})"
        )
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": f"{DOMAIN}_comparison_{city}",
                "title": f"Fuel price comparison ready - {city.capitalize()}",
                "message": message,
            },
            blocking=False,
        )
        notified = set(state.get("notified", []))
        notified.add(city)
        state["notified"] = sorted(notified)
        await _save_state(hass, state)
    except Exception:  # noqa: BLE001 -- never break the sensor on notify
        _LOGGER.warning(
            "Could not send comparison-ready notification for '%s'.",
            city,
            exc_info=True,
        )
        return False
    _LOGGER.info("Sent comparison-ready notification for city '%s'.", city)
    return True
