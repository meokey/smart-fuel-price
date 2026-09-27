"""
Base provider interface for Smart Fuel Price.
All data source plugins must inherit from this class.
"""

import logging
import re
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


class BaseFuelPriceProvider(ABC):
    """Abstract Base Class for Fuel Price Providers with built-in Defensiveness."""

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
            "state": None,
            "tomorrow_price": None,
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
