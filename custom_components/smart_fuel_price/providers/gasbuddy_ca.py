"""GasBuddy (per-station) Provider.

Unlike the other providers, GasBuddy has no city-level average or
forecast -- gasbuddy.com/gaspricemap is a live, user-reported price MAP
of individual stations. This provider therefore takes a specific station
ID (not a city) and a fuel grade, returning that station's current price
for that grade.

Endpoint discovered via Red5d/ha-gasbuddy
(https://github.com/Red5d/ha-gasbuddy) -- thanks for the legwork on
reverse-engineering this. Our multi-station / multi-grade / config-flow
handling is new; the request shape below is theirs.

    POST https://www.gasbuddy.com/gaspricemap/station
    data: {"id": <station_id>, "fuelTypeId": "1"}

Response (abridged):
    {
      "station": {
        "Name": "...", "Address": "...", "City": "...", "State": "...",
        "ZipCode": "...", "Lat": ..., "Lng": ...,
        "APIFuel": [{"Id": 1, "Available": true, "DisplayName": "Regular"}, ...],
        "Fuels": [{"FuelType": 1, "CreditPrice": {
            "Amount": 164.9, "TimePosted": "/Date(1758931200000)/"  # cents per litre
        }}, ...]
      }
    }

TimePosted is .NET JSON-date format: "/Date(<epoch_ms>)/".

ROBUSTNESS NOTES:
  * One response already contains every fuel grade for a station, but
    each (station, grade) sensor used to fetch independently -- meaning
    4 grades on one station meant 4 redundant requests per poll cycle.
    _fetch_station_json() now caches the raw response per station_id at
    the class level (shared across every GasBuddyStationProvider
    instance in this process), so only the first grade's poll in a given
    window actually hits the network. This matters doubly now that
    GasBuddy appears to have tightened bot-detection (observed firsthand
    via the website's own UI returning "An error occurred retrieving
    stations for this area", not just via this integration) -- fewer
    redundant requests means less exposure to that.
  * HTTP 403/429 are treated as a distinct, expected "rate-limited or
    temporarily blocked" case with its own log message, rather than
    falling through to the generic network-error path -- so this shows
    up clearly in HA's log as "try again later", not "something is
    broken".

Grade-name matching is deliberately loose (see _GRADE_ALIASES) since the
exact DisplayName strings GasBuddy uses for non-Regular grades haven't
been confirmed against a live sample as of this writing -- tighten once
verified.

To find a station ID: open https://www.gasbuddy.com/gaspricemap, click a
station's price bubble, click through to its page, and read the number
at the end of the URL (https://www.gasbuddy.com/station/<id>).
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import BaseFuelPriceProvider, RateLimitedError

_LOGGER = logging.getLogger(__name__)

_DOTNET_DATE_RE = re.compile(r"/Date\((\d+)\)/")
_MAP_PAGE_URL = "https://www.gasbuddy.com/gaspricemap"

# Loose aliases -- GasBuddy's exact DisplayName strings for non-Regular
# grades haven't been confirmed. Matching ignores case/spaces/hyphens.
_GRADE_ALIASES: dict[str, set[str]] = {
    "regular": {"regular"},
    "midgrade": {"midgrade", "mid", "plus"},
    "premium": {"premium", "super"},
    "diesel": {"diesel"},
}


def _normalize_grade(name: str) -> str:
    return re.sub(r"[\s-]+", "", name.strip().lower())


def _parse_dotnet_date(value: str | None) -> str | None:
    """Convert a .NET JSON date ("/Date(epoch_ms)/") to an ISO string."""
    if not value:
        return None
    match = _DOTNET_DATE_RE.search(value)
    if not match:
        return None
    epoch_seconds = int(match.group(1)) / 1000
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


def _find_fuel(station: dict[str, Any], fuel_grade: str) -> dict[str, Any] | None:
    """Return the station's Fuels entry matching fuel_grade, or None."""
    fuel_names = {
        str(fuel["Id"]): fuel["DisplayName"]
        for fuel in station.get("APIFuel", [])
        if fuel.get("Available")
    }
    wanted_aliases = _GRADE_ALIASES.get(fuel_grade, {fuel_grade})
    return next(
        (
            fuel for fuel in station.get("Fuels", [])
            if _normalize_grade(fuel_names.get(str(fuel.get("FuelType")), "")) in wanted_aliases
        ),
        None,
    )


class GasBuddyStationProvider(BaseFuelPriceProvider):
    """Provider for a single GasBuddy station + fuel grade.

    Takes a station ID in place of a city (see the base `city` arg) --
    there is no per-city list here, so get_supported_cities() and
    discover_cities() are intentionally left at their base defaults.
    """

    API_URL = "https://www.gasbuddy.com/gaspricemap/station"

    # Shared across every instance in this process -- see module
    # docstring. {station_id: (fetched_at_epoch, raw_json)}
    _station_cache: dict[str, tuple[float, dict]] = {}
    _CACHE_TTL_SECONDS = 20 * 60  # a bit under the 30-min scan_interval

    # Set while a forced (manual) refresh is in flight: _fetch_station_json
    # must then skip the shared class-level cache too, or "Manual refresh"
    # would keep serving the cached payload for up to 20 minutes without
    # ever hitting the network. Per-instance flag; base.get_data() holds
    # this instance's lock across check-and-fetch, so it can't leak
    # across concurrent calls on the same instance.
    _force_station_fetch = False

    # Live per-station prices: serving the last known price on a failed
    # fetch (rate-limit etc.) beats showing unknown.
    allow_stale_on_failure = True

    @property
    def cache_key(self) -> str:
        return f"gasbuddy:{self.station_id}:{self.fuel_grade}"

    def __init__(self, station_id: str, fuel_grade: str = "regular", **kwargs: Any) -> None:
        super().__init__(city=str(station_id), **kwargs)
        self.fuel_grade = fuel_grade.lower()

    @property
    def station_id(self) -> str:
        return self._city

    @property
    def name(self) -> str:
        return "GasBuddy"

    @property
    def sensor_name(self) -> str:
        return f"Current Price ({self.fuel_grade.capitalize()})"

    @property
    def native_unit_of_measurement(self) -> str:
        # Amount is reported in cents per litre; keep the raw value and
        # label it ¢/L (Canadian pump convention, consistent with Gas Wizard).
        return "¢/L"

    @property
    def scan_interval(self) -> timedelta:
        # Unofficial/reverse-engineered endpoint -- kept conservative
        # relative to how "live" the underlying data actually is.
        return timedelta(minutes=30)

    @classmethod
    def _clear_station_cache(cls) -> None:
        """Clear the shared per-station cache. Exposed mainly for tests."""
        cls._station_cache.clear()

    @property
    def source_url(self) -> str | None:
        # Verified: https://www.gasbuddy.com/station/<id> renders the
        # station's page (name, address, community prices).
        return f"https://www.gasbuddy.com/station/{self.station_id}"

    def get_data(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return fuel data; a forced refresh bypasses BOTH cache layers.

        The base implementation only skips the per-instance TTL cache --
        without this override the shared per-station JSON cache
        (``_station_cache``) would still be served for up to 20 minutes,
        making "Manual refresh" a no-op network-wise.
        """
        self._force_station_fetch = force_refresh
        try:
            return super().get_data(force_refresh)
        finally:
            self._force_station_fetch = False

    def check_station_grades(self, fuel_grades: list[str]) -> tuple[bool, list[str]]:
        """Validate a station ID and grade selection with a single fetch.

        Returns ``(station_valid, missing_grades)``: ``station_valid`` is
        False when the station itself can't be resolved (bad ID, or a
        rate-limit/bot-block meant the payload couldn't be confirmed);
        otherwise ``missing_grades`` lists the selected grades this
        station doesn't offer. Used by the config flow so a typo'd grade
        is caught at setup time, not at the first sensor poll.
        """
        try:
            payload = self._fetch_station_json()
        except RateLimitedError as err:
            _LOGGER.info("[%s] Station check rate-limited, treating as unconfirmed: %s", self.name, err)
            return False, list(fuel_grades)
        station = (payload or {}).get("station")
        if not station:
            return False, list(fuel_grades)
        missing = [g for g in fuel_grades if _find_fuel(station, g) is None]
        return True, missing

    def _fetch_station_json(self) -> dict[str, Any] | None:
        """Fetch (or reuse a recent cached copy of) this station's full
        JSON payload. Returns None on any failure (bad response, rate
        limit, non-JSON) -- callers treat that as is_valid: False."""
        now = time.time()
        if not self._force_station_fetch:
            cached = GasBuddyStationProvider._station_cache.get(self.station_id)
            if cached and (now - cached[0]) < self._CACHE_TTL_SECONDS:
                return cached[1]

        # Prime the session the way a real browser would (load the map
        # page, which sets any cookies the API call might expect) before
        # the actual data POST. Failure here is non-fatal -- fall through
        # to the POST regardless, since we don't know for certain this
        # is required.
        try:
            self._session.get(_MAP_PAGE_URL, timeout=self._timeout)
        except Exception as prime_err:  # noqa: BLE001 -- best-effort only
            _LOGGER.debug("[%s] Session priming GET failed (continuing anyway): %s", self.name, prime_err)

        response = self._session.post(
            self.API_URL,
            data={"id": self.station_id, "fuelTypeId": "1"},
            timeout=self._timeout,
        )

        if response.status_code in (403, 429):
            # Handled transient: base.fetch_data() catches this and marks the
            # result rate-limited (not a generic failure), and get_data()
            # falls back to the cached price when one exists.
            raise RateLimitedError(
                f"Station '{self.station_id}' got HTTP {response.status_code} "
                "-- rate-limiting or temporary bot-protection; will try again "
                "on the next scheduled poll."
            )

        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError:
            _LOGGER.warning(
                "[%s] Station '%s' returned a non-JSON response (status %s). "
                "GasBuddy may have added bot protection since this endpoint was "
                "last confirmed working. First 200 chars: %r",
                self.name, self.station_id, response.status_code, response.text[:200],
            )
            return None

        GasBuddyStationProvider._station_cache[self.station_id] = (now, payload)
        return payload

    def _parse_data(self) -> dict[str, Any]:
        payload = self._fetch_station_json()
        if payload is None:
            return {"is_valid": False}

        station = payload.get("station")
        if not station:
            _LOGGER.warning(
                "[%s] No station data returned for id '%s' -- check the ID.",
                self.name, self.station_id,
            )
            return {"is_valid": False}

        matched_fuel = _find_fuel(station, self.fuel_grade)
        if matched_fuel is None:
            available = [
                fuel["DisplayName"]
                for fuel in station.get("APIFuel", [])
                if fuel.get("Available")
            ]
            _LOGGER.warning(
                "[%s] Station '%s' (%s) has no '%s' fuel grade available. "
                "Available grades: %s",
                self.name, self.station_id, station.get("Name", "?"),
                self.fuel_grade, available,
            )
            return {"is_valid": False}

        price = matched_fuel.get("CreditPrice", {}).get("Amount")
        if price is None:
            return {"is_valid": False}

        # Amount is already in cents per litre (e.g. 168.9); pass it
        # through raw -- the "¢/L" unit label carries the meaning.
        return {
            "state": price,
            "tomorrow_price": None,  # GasBuddy is a live snapshot, not a forecast
            "current_price": price,
            "trend": "unknown",  # no prior-price comparison available here
            "effective_date_str": "N/A",  # not applicable -- see last_reported_str
            "last_reported_str": _parse_dotnet_date(
                matched_fuel.get("CreditPrice", {}).get("TimePosted")
            ) or "N/A",
            "is_valid": True,
            "is_rising": False,
            "is_dropping": False,
            "fuel_grade": self.fuel_grade,
            "station_id": self.station_id,
            "station_name": station.get("Name"),
            "address": station.get("Address"),
            "city": station.get("City"),  # overwrites base default (was the station ID)
            "province_or_state": station.get("State"),
        }
