"""
Base provider interface for Smart Fuel Price.
All data source plugins must inherit from this class.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from abc import ABC, abstractmethod
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

# Several target sites (and third-party widgets embedded on them) block or
# mis-serve requests carrying the default python-requests User-Agent string.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
}

# Matches the first int/decimal number in a string, e.g. "7 cent(s)" -> "7"
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")

def first_number(text: str | None) -> float | None:
    """Extract the first int/decimal number found in text, or None."""
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    return float(match.group(1)) if match else None


def cents_to_dollars(cents: float | None) -> float | None:
    """Convert a cents/litre value to dollars/litre, rounded to 3 places."""
    if cents is None:
        return None
    return round(cents / 100, 3)

def trend_fields(change_cents: float | None) -> dict[str, Any]:
    """Map a signed price change (¢/L) to trend / is_rising / is_dropping."""
    if change_cents is None:
        return {"trend": "unknown", "is_rising": False, "is_dropping": False}
    if change_cents > 0:
        return {"trend": "rising", "is_rising": True, "is_dropping": False}
    if change_cents < 0:
        return {"trend": "falling", "is_rising": False, "is_dropping": True}
    return {"trend": "stable", "is_rising": False, "is_dropping": False}

class BaseFuelPriceProvider(ABC):
    """Abstract Base Class for Fuel Price Providers with built-in Defensiveness."""

    # When True, a failed fetch falls back to the last cached payload
    # (marked stale=True) instead of returning invalid/unknown. Only for
    # providers where slightly old data beats no data -- e.g. live prices
    # behind rate limits. Forecast providers keep this False: a stale
    # forecast would be actively misleading.
    allow_stale_on_failure: bool = False

    def __init__(
        self,
        city: str,
        api_key: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._city = city.lower().strip()
        self._api_key = api_key
        self._timeout = 10  # Hard 10-second network timeout boundary.
        self._session = session or self._build_session()
        # Local fetch cache: last payload + when it was fetched.
        # cache_ttl may be overridden (e.g. from the HA options flow);
        # None means "fall back to this provider's scan_interval".
        self.cache_ttl: timedelta | None = None
        self._cached_data: dict[str, Any] | None = None
        self._cached_at: datetime | None = None
        self._last_attempt_at: datetime | None = None

    @classmethod
    def _build_session(cls) -> requests.Session:
        """Return a requests.Session pre-configured with browser-like headers."""
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        return session

    @property
    def city(self) -> str:
        """Return selected city."""
        return self._city

    @property
    def api_key(self) -> str | None:
        """Return the configured API key, if any."""
        return self._api_key

    @property
    @abstractmethod
    def name(self) -> str:
        """Return provider name."""

    @property
    def requires_api_key(self) -> bool:
        """Whether this provider needs a user-supplied API key to function.

        Web-scraping providers should leave this as False (the default).
        Providers wrapping a paid/keyed API should override this to True
        so the config flow knows to prompt for it.
        """
        return False

    @property
    def scan_interval(self) -> timedelta:
        """Suggested minimum time between fetches for this provider.

        Providers backed by a slow-changing source (a once-daily
        forecast) should keep this long to avoid hammering the site;
        providers backed by a live, frequently-updated feed should
        override with something shorter.
        """
        return timedelta(hours=4)

    @property
    def sensor_name(self) -> str:
        """Entity name shown in HA, e.g. 'Price Change', 'Current Price'."""
        return "Price Change"

    @property
    def native_unit_of_measurement(self) -> str:
        """Unit of the sensor's native_value."""
        return "¢/L"

    @classmethod
    def get_supported_cities(cls) -> list[str]:
        """Return the static, known-good list of supported cities/regions."""
        return []

    @classmethod
    def discover_cities(cls) -> dict[str, str] | None:
        """Optionally probe the live source for its current city list.

        Returns a mapping of {city_slug: display_name}, or None if this
        provider doesn't support (or hasn't implemented) live discovery --
        callers should then fall back to get_supported_cities().

        This is intentionally NOT abstract: most providers can rely on a
        maintained static list. Implementations should keep the network
        call cheap and idempotent; callers (e.g. config_flow) are expected
        to cache the result between calls (e.g. via HA's Store helper) --
        this method itself does no caching.
        """
        return None

    def fetch_data(self) -> dict[str, Any]:
        """
        Template method: Fetch and parse fuel price data securely.
        Handles networking, timeouts, and exception boundaries.
        """
        # Fail-safe default values
        result: dict[str, Any] = {
            "state": None,  # signed price change in ¢/L (tomorrow - current)
            "tomorrow_price": None,  # forecast average, ¢/L
            "current_price": None,  # today's average, ¢/L
            "trend": "unknown",
            "effective_date_str": "N/A",
            "is_valid": False,
            "is_dropping": False,
            "is_rising": False,
            "provider_name": self.name,
            "city": self.city,
        }

        try:
            parsed_data = self._parse_data()
            if parsed_data:
                result.update(parsed_data)
        except requests.exceptions.RequestException as req_err:
            _LOGGER.error("[%s] Network connection error: %s", self.name, req_err)
        except (KeyError, IndexError, ValueError, TypeError) as parse_err:
            _LOGGER.error("[%s] Data parsing/boundary error: %s", self.name, parse_err)
        except Exception as e:  # noqa: BLE001 - defensive top-level boundary
            _LOGGER.error("[%s] Unexpected error during data extraction: %s", self.name, e)

        return result

    @property
    def cache_key(self) -> str:
        """Stable key identifying this provider's cache slot.

        Used for persisting the fetch cache across restarts. Providers
        with extra identity dimensions (e.g. GasBuddy's fuel grade)
        must override this.
        """
        return f"{type(self).__name__}:{self._city}"

    def _effective_ttl(self) -> timedelta:
        return self.cache_ttl if self.cache_ttl is not None else self.scan_interval

    def get_data(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return fuel data, reusing the local cache when it is fresh.

        - Within TTL of the last attempt (and not forced): return the
          cached payload with ``from_cache: True`` -- no network call.
        - Otherwise fetch; on success the cache (data + timestamp) is
          refreshed.
        - On a failed fetch with a warm cache: serve the stale payload
          (``from_cache: True, stale: True``) when
          ``allow_stale_on_failure`` is set, else the invalid result.
        """
        now = datetime.now(timezone.utc)
        ttl = self._effective_ttl()
        if (
            not force_refresh
            and self._cached_data is not None
            and self._last_attempt_at is not None
            and now - self._last_attempt_at < ttl
        ):
            cached = dict(self._cached_data)
            cached["from_cache"] = True
            return cached

        self._last_attempt_at = now
        data = self.fetch_data()
        if data.get("is_valid"):
            self._cached_data = dict(data)
            self._cached_at = now
            data["from_cache"] = False
            return data

        if self.allow_stale_on_failure and self._cached_data is not None:
            _LOGGER.info(
                "[%s] Fetch failed; serving last cached data (stale).", self.name
            )
            stale = dict(self._cached_data)
            stale["from_cache"] = True
            stale["stale"] = True
            return stale

        data["from_cache"] = False
        return data

    def hydrate_cache(self, data: dict[str, Any], fetched_at: datetime) -> None:
        """Restore a previously persisted cache (e.g. after HA restart)."""
        self._cached_data = dict(data)
        self._cached_at = fetched_at
        self._last_attempt_at = fetched_at

    @abstractmethod
    def _parse_data(self) -> dict[str, Any]:
        """
        Internal parsing logic to be implemented by child classes.
        Should return a dictionary of successfully parsed keys to update
        the base result.
        """

    def _get(self, url: str, **kwargs: Any) -> requests.Response:
        """GET a URL using the shared session, headers and timeout."""
        kwargs.setdefault("timeout", self._timeout)
        response = self._session.get(url, **kwargs)
        response.raise_for_status()
        return response

