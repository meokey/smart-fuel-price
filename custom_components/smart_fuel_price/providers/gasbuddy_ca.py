"""GasBuddy (per-station) Provider.

Unlike the other providers, GasBuddy has no city-level average or
forecast -- gasbuddy.com/gaspricemap is a live, user-reported price MAP
of individual stations. This provider therefore takes a specific station
ID (not a city) and a fuel grade, returning that station's current price
for that grade.

API approach -- credit to firstof9/py-gasbuddy and firstof9/ha-gasbuddy
(both MIT) for reverse-engineering GasBuddy's official GraphQL API and
the CSRF-token flow; thanks for the legwork. This provider is an
independent, sync/requests-based implementation of the same public API
(no code copied).

Why GraphQL: the older ``POST /gaspricemap/station`` endpoint
(discovered via Red5d/ha-gasbuddy) started getting intermittently
challenged by Cloudflare's "Just a moment..." interstitial in Oct 2026
(HTTP 403 for plain sessions), which surfaced as sensors stuck at
Unknown with "Rate limited" status. The GraphQL API is what
gasbuddy.com itself uses, so it passes with the site's own CSRF token.

Flow (read-only):
    1. GET https://www.gasbuddy.com/home -> extract ``window.gbcsrf``
    2. POST https://www.gasbuddy.com/graphql
       {"operationName": "GetStation", "query": ..., "variables": {"id": ...}}
       with headers including the gbcsrf token
    3. Parse ``data.station.prices[]`` by ``fuelProduct``.

A prices[] entry looks like:
    {"fuelProduct": "regular_gas", "longName": "Regular (85-87 Octane)",
     "credit": {"price": 165.9, "formattedPrice": "165.9",
                "postedTime": "...", "nickname": "..."},
     "cash": {...}}

ROBUSTNESS NOTES:
  * One response already contains every fuel grade for a station, so the
    raw station payload is cached per station_id at the class level
    (shared across every GasBuddyStationProvider instance in this
    process) -- only the first grade's poll in a given window actually
    hits the network.
  * The CSRF token is cached per process and refreshed when missing or
    after a 401/403 (the token may go stale); one retry with a fresh
    token is attempted before giving up.
  * HTTP 403/429 are treated as a distinct, expected "rate-limited or
    temporarily blocked" case with its own log message, rather than
    falling through to the generic network-error path.

To find a station ID: open https://www.gasbuddy.com/gaspricemap, click a
station's price bubble, click through to its page, and read the number
at the end of the URL (https://www.gasbuddy.com/station/<id>).
"""

import logging
import re
import time
from datetime import timedelta
from typing import Any

from .base import BaseFuelPriceProvider, RateLimitedError

_LOGGER = logging.getLogger(__name__)

_GRAPHQL_URL = "https://www.gasbuddy.com/graphql"
_HOME_URL = "https://www.gasbuddy.com/home"
_CSRF_RE = re.compile(r'window\.gbcsrf\s*=\s*(["\'])(.*?)\1')

# GraphQL fuelProduct -> our fuel_grade vocabulary. The old endpoint's
# loose DisplayName aliases are gone -- the API's keys are stable.
_FUEL_PRODUCT_TO_GRADE: dict[str, str] = {
    "regular_gas": "regular",
    "midgrade_gas": "midgrade",
    "premium_gas": "premium",
    "diesel": "diesel",
}

# Trimmed to the fields this provider actually uses (the full
# GetStation query in py-gasbuddy also selects brands, amenities,
# hours, offers -- not needed here).
_GET_STATION_QUERY = """
query GetStation($id: ID!) {
  station(id: $id) {
    id
    name
    phone
    priceUnit
    currency
    latitude
    longitude
    address {
      line1
      line2
      locality
      region
      postalCode
      country
    }
    prices {
      fuelProduct
      longName
      credit { price formattedPrice postedTime nickname }
      cash { price formattedPrice postedTime nickname }
    }
  }
}
""".strip()


def _extract_csrf_token(home_html: str) -> str | None:
    """Extract the ``window.gbcsrf`` token from the /home page HTML."""
    match = _CSRF_RE.search(home_html or "")
    return match.group(2) if match else None


class GasBuddyStationProvider(BaseFuelPriceProvider):
    """Provider for a single GasBuddy station + fuel grade.

    Takes a station ID in place of a city (see the base `city` arg) --
    there is no per-city list here, so get_supported_cities() and
    discover_cities() are intentionally left at their base defaults.
    """

    # Shared across every instance in this process -- see module
    # docstring. {station_id: (fetched_at_epoch, station_dict)}
    _station_cache: dict[str, tuple[float, dict]] = {}
    _CACHE_TTL_SECONDS = 20 * 60  # a bit under the 30-min scan_interval

    # CSRF token cache, also process-wide: {token, fetched_at_epoch}.
    _csrf_token: str | None = None
    _csrf_fetched_at: float = 0.0
    _CSRF_TTL_SECONDS = 6 * 3600

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
        # Unofficial/reverse-engineered API -- kept conservative relative
        # to how "live" the underlying data actually is.
        return timedelta(minutes=30)

    @classmethod
    def _clear_station_cache(cls) -> None:
        """Clear the shared per-station cache. Exposed mainly for tests."""
        cls._station_cache.clear()
        cls._csrf_token = None
        cls._csrf_fetched_at = 0.0

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

    @classmethod
    def _get_csrf_token(cls, session, timeout: int) -> str | None:
        """Return a cached CSRF token, fetching a fresh one if needed."""
        now = time.time()
        if cls._csrf_token and (now - cls._csrf_fetched_at) < cls._CSRF_TTL_SECONDS:
            return cls._csrf_token
        try:
            response = session.get(_HOME_URL, timeout=timeout)
            token = _extract_csrf_token(response.text)
        except Exception as err:  # noqa: BLE001 -- token fetch is best-effort
            _LOGGER.debug("[GasBuddy] CSRF token fetch failed: %s", err)
            return None
        if not token:
            _LOGGER.debug("[GasBuddy] No gbcsrf token found on the home page")
            return None
        cls._csrf_token = token
        cls._csrf_fetched_at = now
        return token

    @classmethod
    def _drop_csrf_token(cls) -> None:
        cls._csrf_token = None
        cls._csrf_fetched_at = 0.0

    def _graphql_headers(self, token: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Origin": "https://www.gasbuddy.com",
            "Referer": _HOME_URL,
            "apollo-require-preflight": "true",
            "gbcsrf": token,
        }

    def _fetch_station_json(self) -> dict[str, Any] | None:
        """Fetch (or reuse a recent cached copy of) this station's data.

        Returns the ``data.station`` dict, or None on any failure (bad
        response, rate limit, non-JSON, missing token) -- callers treat
        that as is_valid: False.
        """
        now = time.time()
        if not self._force_station_fetch:
            cached = GasBuddyStationProvider._station_cache.get(self.station_id)
            if cached and (now - cached[0]) < self._CACHE_TTL_SECONDS:
                return cached[1]

        token = self._get_csrf_token(self._session, self._timeout)
        if not token:
            _LOGGER.info(
                "[%s] Could not obtain a CSRF token -- treating as rate-limited; "
                "will try again on the next scheduled poll.", self.name,
            )
            raise RateLimitedError("No CSRF token available")

        payload = {
            "operationName": "GetStation",
            "query": _GET_STATION_QUERY,
            "variables": {"id": self.station_id},
        }

        response = None
        for attempt in range(2):
            response = self._session.post(
                _GRAPHQL_URL,
                json=payload,
                headers=self._graphql_headers(token),
                timeout=self._timeout,
            )
            if response.status_code in (401, 403) and attempt == 0:
                # Token may have gone stale -- drop it, fetch a fresh one,
                # and retry once before giving up.
                _LOGGER.debug(
                    "[%s] GraphQL returned %s; refreshing CSRF token and retrying",
                    self.name, response.status_code,
                )
                self._drop_csrf_token()
                token = self._get_csrf_token(self._session, self._timeout)
                if not token:
                    break
                continue
            break

        if response is None or response.status_code in (403, 429):
            # Handled transient: base.fetch_data() catches this and marks the
            # result rate-limited (not a generic failure), and get_data()
            # falls back to the cached price when one exists.
            raise RateLimitedError(
                f"Station '{self.station_id}' got HTTP "
                f"{response.status_code if response is not None else 'n/a'} "
                "-- rate-limiting or temporary bot-protection; will try again "
                "on the next scheduled poll."
            )

        response.raise_for_status()

        try:
            body = response.json()
        except ValueError:
            _LOGGER.warning(
                "[%s] Station '%s' returned a non-JSON response (status %s). "
                "First 200 chars: %r",
                self.name, self.station_id, response.status_code, response.text[:200],
            )
            return None

        if isinstance(body, dict) and body.get("errors"):
            _LOGGER.warning(
                "[%s] GraphQL errors for station '%s': %s",
                self.name, self.station_id, str(body["errors"])[:200],
            )
            return None

        station = (body.get("data") or {}).get("station") if isinstance(body, dict) else None
        if not station:
            _LOGGER.warning(
                "[%s] No station data returned for id '%s' -- check the ID.",
                self.name, self.station_id,
            )
            return None

        GasBuddyStationProvider._station_cache[self.station_id] = (now, station)
        return station

    def _find_price_entry(self, station: dict[str, Any]) -> dict[str, Any] | None:
        """Return the station's prices[] entry matching fuel_grade."""
        wanted = self.fuel_grade
        return next(
            (
                entry for entry in station.get("prices") or []
                if _FUEL_PRODUCT_TO_GRADE.get(entry.get("fuelProduct")) == wanted
            ),
            None,
        )

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
            station = self._fetch_station_json()
        except RateLimitedError as err:
            _LOGGER.info("[%s] Station check rate-limited, treating as unconfirmed: %s", self.name, err)
            return False, list(fuel_grades)
        if not station:
            return False, list(fuel_grades)
        offered = {
            _FUEL_PRODUCT_TO_GRADE.get(entry.get("fuelProduct"))
            for entry in station.get("prices") or []
        }
        missing = [g for g in fuel_grades if g.lower() not in offered]
        return True, missing

    def _parse_data(self) -> dict[str, Any]:
        station = self._fetch_station_json()
        if station is None:
            return {"is_valid": False}

        matched = self._find_price_entry(station)
        if matched is None:
            available = sorted(
                {
                    _FUEL_PRODUCT_TO_GRADE.get(entry.get("fuelProduct"), entry.get("fuelProduct"))
                    for entry in station.get("prices") or []
                }
            )
            _LOGGER.warning(
                "[%s] Station '%s' (%s) has no '%s' fuel grade available. "
                "Available grades: %s",
                self.name, self.station_id, station.get("name", "?"),
                self.fuel_grade, available,
            )
            return {"is_valid": False}

        credit = matched.get("credit") or {}
        cash = matched.get("cash") or {}
        price = credit.get("price") or cash.get("price")
        if not price:
            return {"is_valid": False}

        # Price is already in cents per litre (e.g. 165.9); pass it
        # through raw -- the "¢/L" unit label carries the meaning.
        address = station.get("address") or {}
        return {
            "state": price,
            "tomorrow_price": None,  # GasBuddy is a live snapshot, not a forecast
            "current_price": price,
            "trend": "unknown",  # no prior-price comparison available here
            "effective_date_str": "N/A",  # not applicable -- see last_reported_str
            "last_reported_str": (credit.get("postedTime") or cash.get("postedTime")) or "N/A",
            "is_valid": True,
            "is_rising": False,
            "is_dropping": False,
            "fuel_grade": self.fuel_grade,
            "station_id": self.station_id,
            "station_name": station.get("name"),
            "phone": station.get("phone"),
            "address": " ".join(
                part for part in (address.get("line1"), address.get("line2")) if part
            ),
            "city": address.get("locality"),  # overwrites base default (was the station ID)
            "province_or_state": address.get("region"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
            "price_unit": station.get("priceUnit"),
            "currency": station.get("currency"),
        }
