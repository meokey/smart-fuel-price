"""GasBuddy (per-station) Provider.

Unlike the other providers, GasBuddy has no city-level average or
forecast -- gasbuddy.com/gaspricemap is a live, user-reported price MAP
of individual stations. This provider therefore takes a specific station
ID (not a city) and returns that station's current Regular price.

Endpoint discovered via Red5d/ha-gasbuddy
(https://github.com/Red5d/ha-gasbuddy) -- thanks for the legwork on
reverse-engineering this. Our multi-station / config-flow handling is
new; the request shape below is theirs.

    POST https://www.gasbuddy.com/gaspricemap/station
    data: {"id": <station_id>, "fuelTypeId": "1"}

Response (abridged):
    {
      "station": {
        "Name": "...", "Address": "...", "City": "...", "State": "...",
        "ZipCode": "...", "Lat": ..., "Lng": ...,
        "APIFuel": [{"Id": 1, "Available": true, "DisplayName": "Regular"}, ...],
        "Fuels": [{"FuelType": 1, "CreditPrice": {
            "Amount": 1.649, "TimePosted": "/Date(1758931200000)/"
        }}, ...]
      }
    }

TimePosted is .NET JSON-date format: "/Date(<epoch_ms>)/".

To find a station ID: open https://www.gasbuddy.com/gaspricemap, click a
station's price bubble, click through to its page, and read the number
at the end of the URL (https://www.gasbuddy.com/station/<id>).
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

_DOTNET_DATE_RE = re.compile(r"/Date\((\d+)\)/")


def _parse_dotnet_date(value: str | None) -> str | None:
    """Convert a .NET JSON date ("/Date(epoch_ms)/") to an ISO string."""
    if not value:
        return None
    match = _DOTNET_DATE_RE.search(value)
    if not match:
        return None
    epoch_seconds = int(match.group(1)) / 1000
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


class GasBuddyStationProvider(BaseFuelPriceProvider):
    """Provider for a single GasBuddy station, by station ID.

    Takes a station ID in place of a city (see the base `city` arg) --
    there is no per-city list here, so get_supported_cities() and
    discover_cities() are intentionally left at their base defaults.
    """

    API_URL = "https://www.gasbuddy.com/gaspricemap/station"
    FUEL_GRADE = "regular"  # matches the single-grade convention used by
                             # every other provider in this integration

    def __init__(self, station_id: str, **kwargs: Any) -> None:
        super().__init__(city=str(station_id), **kwargs)

    @property
    def station_id(self) -> str:
        return self._city

    @property
    def name(self) -> str:
        return "GasBuddy"

    @property
    def sensor_name(self) -> str:
        return "Current Price"

    @property
    def native_unit_of_measurement(self) -> str:
        return "$"

    def _parse_data(self) -> dict[str, Any]:
        response = self._session.post(
            self.API_URL,
            data={"id": self.station_id, "fuelTypeId": "1"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()

        station = payload.get("station")
        if not station:
            _LOGGER.warning(
                "[%s] No station data returned for id '%s' -- check the ID.",
                self.name, self.station_id,
            )
            return {"is_valid": False}

        fuel_names = {
            str(fuel["Id"]): fuel["DisplayName"]
            for fuel in station.get("APIFuel", [])
            if fuel.get("Available")
        }

        regular_fuel = next(
            (
                fuel for fuel in station.get("Fuels", [])
                if fuel_names.get(str(fuel.get("FuelType")), "").lower() == self.FUEL_GRADE
            ),
            None,
        )
        if regular_fuel is None:
            _LOGGER.warning(
                "[%s] Station '%s' (%s) has no '%s' fuel grade available.",
                self.name, self.station_id, station.get("Name", "?"), self.FUEL_GRADE,
            )
            return {"is_valid": False}

        price = regular_fuel.get("CreditPrice", {}).get("Amount")
        if price is None:
            return {"is_valid": False}

        return {
            "state": price,
            "tomorrow_price": None,  # GasBuddy is a live snapshot, not a forecast
            "current_price": price,
            "trend": "unknown",  # no prior-price comparison available here
            "effective_date_str": _parse_dotnet_date(
                regular_fuel.get("CreditPrice", {}).get("TimePosted")
            ) or "N/A",
            "is_valid": True,
            "is_rising": False,
            "is_dropping": False,
            "station_id": self.station_id,
            "station_name": station.get("Name"),
            "address": station.get("Address"),
            "city": station.get("City"),  # overwrites base default (was the station ID)
            "province_or_state": station.get("State"),
        }
