"""Home-Assistant-aware tests for config_flow.py.

Uses affordableenergy_ca for the city-based path deliberately: its
discover_cities() isn't implemented (returns the base class's None
default), so _get_cities_for_provider falls straight through to the
static CITY_MAP with no network call needed -- keeps this test
hermetic without mocking that path.
"""
import pytest

pytest.importorskip("homeassistant", reason="needs pytest-homeassistant-custom-component, CI-only")

pytestmark = pytest.mark.ha_integration

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_fuel_price.const import DOMAIN

@pytest.mark.asyncio
async def test_user_step_then_details_step_for_gaswizard(hass):
    """Step 1 (provider) -> step 2 (city) happy path, and the fields
    shown in step 2 must match the provider just picked -- this is the
    exact behavior that was broken in the single-step flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"provider": "affordableenergy_ca"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "details"
    assert "city" in result["data_schema"].schema

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"city": "toronto"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Smart Fuel Price - Toronto - Canada (Gas Wizard)"
    assert result["data"]["city"] == "toronto"

@pytest.mark.asyncio
async def test_details_step_rejects_unsupported_city(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"provider": "affordableenergy_ca"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"city": "nonexistent_city_xyz"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "unsupported_city"

@pytest.mark.asyncio
async def test_gasbuddy_details_step_shows_station_fields_not_city(hass):
    """The original bug report: GasBuddy showed a City field instead
    of Station IDs until a failed submit forced a re-render."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"provider": "gasbuddy_ca"}
    )
    assert result["step_id"] == "details"
    assert "station_ids" in result["data_schema"].schema
    assert "city" not in result["data_schema"].schema

@pytest.mark.asyncio
async def test_gasbuddy_requires_station_ids(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"provider": "gasbuddy_ca"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"station_ids": "", "fuel_grades": ["regular"]}
    )
    assert result["errors"]["base"] == "station_ids_required"

@pytest.mark.asyncio
async def test_gasbuddy_requires_fuel_grade(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"provider": "gasbuddy_ca"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"station_ids": "205748", "fuel_grades": []}
    )
    assert result["errors"]["base"] == "fuel_grade_required"

@pytest.mark.asyncio
async def test_gasbuddy_happy_path_creates_entry(hass):
    with patch(
        "custom_components.smart_fuel_price.providers.gasbuddy_ca."
        "GasBuddyStationProvider.fetch_data",
        return_value={"is_valid": True, "state": 1.649},
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"provider": "gasbuddy_ca"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"station_ids": "205748, 123456", "fuel_grades": ["regular", "diesel"]},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["station_ids"] == "205748, 123456"
    assert result["data"]["fuel_grades"] == ["regular", "diesel"]

@pytest.mark.asyncio
async def test_duplicate_entry_is_aborted(hass):
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="affordableenergy_ca_toronto",
        data={"provider": "affordableenergy_ca", "city": "toronto"},
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"provider": "affordableenergy_ca"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"city": "toronto"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
