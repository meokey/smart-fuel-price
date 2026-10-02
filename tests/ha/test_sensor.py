"""Home-Assistant-aware tests for sensor.py."""

import pytest

pytest.importorskip("homeassistant", reason="needs pytest-homeassistant-custom-component, CI-only")

pytestmark = pytest.mark.ha_integration

from unittest.mock import patch

from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_fuel_price.const import DOMAIN

_GASWIZARD_RESULT = {
    "state": -7.0,
    "tomorrow_price": 181.9,
    "current_price": 188.9,
    "trend": "falling",
    "is_valid": True,
    "is_rising": False,
    "is_dropping": True,
    "provider_name": "Affordable Energy (Gas Wizard)",
    "city": "toronto",
    "effective_date_str": "Monday Sep 28, 2026",
}


async def test_city_provider_creates_one_sensor(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="affordableenergy_ca_toronto",
        data={"provider": "affordableenergy_ca", "city": "toronto"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smart_fuel_price.providers.affordableenergy_ca."
        "AffordableEnergyCaProvider.fetch_data",
        return_value=_GASWIZARD_RESULT,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    states = hass.states.async_all("sensor")
    assert len(states) == 1
    assert states[0].state == "-7.0"
    assert states[0].attributes["current_price"] == 188.9


async def test_gasbuddy_multi_grade_shares_one_device(hass):
    """Regression test for the device-fragmentation bug: two fuel
    grades for the SAME station must land on ONE HA device, not two."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="gasbuddy_ca_205748_diesel_regular",
        data={
            "provider": "gasbuddy_ca",
            "station_ids": "205748",
            "fuel_grades": ["regular", "diesel"],
        },
    )
    entry.add_to_hass(hass)

    def _fake_fetch(self):
        return {
            "state": 1.649 if self.fuel_grade == "regular" else 1.799,
            "is_valid": True,
            "city": "Oshawa",
            "station_name": "Costco",
            "fuel_grade": self.fuel_grade,
        }

    with patch(
        "custom_components.smart_fuel_price.providers.gasbuddy_ca."
        "GasBuddyStationProvider.fetch_data",
        new=_fake_fetch,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    states = hass.states.async_all("sensor")
    assert len(states) == 2  # one entity per fuel grade

    entity_registry = er.async_get(hass)
    device_ids = {
        entity_registry.async_get(state.entity_id).device_id for state in states
    }
    assert len(device_ids) == 1  # ...but ONE shared device
