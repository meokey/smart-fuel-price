"""CityNews Canada Fuel Price Provider.

citynews.ca runs a network of city-specific sites, each with its own
"Gas Prices" section -- but the underlying widget differs by city:

  * "forecast" layout -- CONFIRMED live on Toronto, Ottawa and Kitchener,
    all at /gas-prices/. Parsed by vendor_widgets.parse_en_pro_forecast().
    Gives a genuine next-day price forecast.

  * "gasbuddy" layout -- Calgary, at /calgary-gas-prices/. The page embeds
    GasBuddy's average-price widget: the plain-GET HTML only carries a
    placeholder plus <script src="https://df.gasbuddy.com/feed.gdf?...">
    tags; the browser then GETs each feed URL and the response JavaScript
    writes the price into the DOM
    (document.getElementById('price126610').innerHTML='169.1'). No JS
    execution is needed -- vendor_widgets.parse_gasbuddy_report() replays
    the second GET and regexes the price out. Gives the *current average*,
    not a forecast.

Other citynews.ca markets (Vancouver, Edmonton, Winnipeg, Montreal,
Halifax) exist but haven't been checked -- see CITY_MAP below.
"""

import logging
import re
from typing import Any

import requests

from . import vendor_widgets
from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

CITY_MAP: dict[str, dict[str, str]] = {
    "toronto": {"subdomain": "toronto", "parser": "forecast"},
    "ottawa": {"subdomain": "ottawa", "parser": "forecast"},
    "kitchener": {"subdomain": "kitchener", "parser": "forecast"},
    "calgary": {"subdomain": "calgary", "parser": "gasbuddy"},
    # Confirmed to exist on citynews.ca's city switcher, but layout not
    # yet visually verified -- add once confirmed:
    # "vancouver": {"subdomain": "vancouver", "parser": "auto"},
    # "edmonton": {"subdomain": "edmonton", "parser": "auto"},
    # "winnipeg": {"subdomain": "winnipeg", "parser": "auto"},
    # "montreal": {"subdomain": "montreal", "parser": "auto"},
    # "halifax": {"subdomain": "halifax", "parser": "auto"},
}

GAS_PRICES_PATH_CANDIDATES = ("gas-prices/", "{subdomain}-gas-prices/")

_CITY_LINK_RE = re.compile(
    r'href="https?://([a-z]+)\.citynews\.ca/?"[^>]*>([^<]+)<', re.IGNORECASE
)


class CityNewsCaProvider(BaseFuelPriceProvider):
    """Provider for CityNews Canada (citynews.ca network of city sites)."""

    BASE_DOMAIN = "citynews.ca"

    @property
    def name(self) -> str:
        return "CityNews Canada"

    def _parser_hint(self) -> str:
        """Which widget layout this instance's city uses."""
        return CITY_MAP.get(self.city, {}).get("parser", "auto")

    @property
    def sensor_name(self) -> str:
        # The gasbuddy layout reports a current average, not a forecast
        # change -- name the entity accordingly.
        if self._parser_hint() == "gasbuddy":
            return "Current Average Price"
        return super().sensor_name

    @property
    def allow_stale_on_failure(self) -> bool:
        # A slightly old average beats no average during outages (same
        # reasoning as the GasBuddy station provider).
        return self._parser_hint() == "gasbuddy"

    @classmethod
    def get_supported_cities(cls) -> list[str]:
        return list(CITY_MAP.keys())

    @classmethod
    def city_has_prices(cls, city: str) -> bool:
        """Whether the city has a parseable gas-prices page.

        Cheap marker check (one plain GET per URL candidate): accepts the
        En-Pro forecast sentence or a GasBuddy widget embed. Used to filter
        live-discovered cities -- markets like Edmonton have a citynews.ca
        site but no gas prices section at all (Oct 2026 probe).
        """
        session = cls._build_session()
        for path_template in GAS_PRICES_PATH_CANDIDATES:
            path = path_template.format(subdomain=city)
            url = f"https://{city}.{cls.BASE_DOMAIN}/{path}"
            try:
                response = session.get(url, timeout=10)
                response.raise_for_status()
                page_html = response.text
            except requests.exceptions.RequestException:
                continue
            if vendor_widgets.parse_en_pro_forecast(page_html):
                return True
            if vendor_widgets.has_gasbuddy_widget(page_html):
                return True
        return False

    @classmethod
    def discover_cities(cls) -> dict[str, str] | None:
        """Best-effort live discovery via citynews.ca's city switcher.

        Candidate list only -- not verified to have a working Gas Prices
        section (see module docstring). Treat an unrecognised slug as
        "parser": "auto" and let _parse_data's cascade sort it out.
        """
        try:
            session = cls._build_session()
            response = session.get(f"https://{cls.BASE_DOMAIN}", timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as err:
            _LOGGER.warning(
                "CityNews city discovery failed, using static list: %s", err
            )
            return None

        matches = _CITY_LINK_RE.findall(response.text)
        if not matches:
            _LOGGER.warning(
                "CityNews city discovery found no city links; using static list."
            )
            return None

        return {slug.lower(): label.strip() for slug, label in matches}

    def _parse_data(self) -> dict[str, Any]:
        city_info = CITY_MAP.get(self.city)
        if not city_info:
            _LOGGER.warning(
                "[%s] City '%s' is not in the known map; falling back to 'toronto'.",
                self.name,
                self.city,
            )
            city_info = CITY_MAP["toronto"]

        subdomain = city_info["subdomain"]
        parser_hint = city_info.get("parser", "auto")

        fetched = self._fetch_gas_prices_page(subdomain, parser_hint)
        if fetched is None:
            _LOGGER.error(
                "[%s] Could not fetch a Gas Prices page for '%s' at any known URL.",
                self.name,
                subdomain,
            )
            return {"city": subdomain, "is_valid": False}

        _page_url, page_html = fetched
        # Remember the winning URL: article slugs rotate, so the device info
        # link must point at the page that actually parsed.
        self._last_source_url = _page_url

        if parser_hint in ("forecast", "auto"):
            parsed = vendor_widgets.parse_en_pro_forecast(page_html)
            if parsed:
                parsed["city"] = subdomain
                return parsed

        if parser_hint in ("gasbuddy", "auto"):
            parsed = vendor_widgets.parse_gasbuddy_report(
                page_html, _page_url, self._get
            )
            if parsed:
                parsed["city"] = subdomain
                return parsed

        _LOGGER.warning(
            "[%s] Could not match a known layout for '%s'. Compare "
            "'view-source:' to the browser-rendered DOM to confirm the "
            "current markup before filing a bug.",
            self.name,
            subdomain,
        )
        return {"city": subdomain, "is_valid": False}

    @property
    def source_url(self) -> str | None:
        """Last successfully parsed article URL (None before first success)."""
        return getattr(self, "_last_source_url", None)

    def _fetch_gas_prices_page(
        self, subdomain: str, parser_hint: str = "auto"
    ) -> tuple[str, str] | None:
        """Try each known URL slug in turn; return (url, html) for the first hit.

        Candidate order is parser-aware: the "{subdomain}-gas-prices/" slug
        is the widget page for gasbuddy-layout cities (Calgary), while
        plain "gas-prices/" soft-404s there (redirects to an old article
        with HTTP 200, so it can't be skipped on status alone).
        """
        if parser_hint == "gasbuddy":
            candidates = ("{subdomain}-gas-prices/", "gas-prices/")
        else:
            candidates = GAS_PRICES_PATH_CANDIDATES
        for path_template in candidates:
            path = path_template.format(subdomain=subdomain)
            url = f"https://{subdomain}.{self.BASE_DOMAIN}/{path}"
            try:
                response = self._get(url)
            except requests.exceptions.HTTPError as err:
                _LOGGER.debug(
                    "[%s] %s returned an error (%s); trying next candidate.",
                    self.name,
                    url,
                    err,
                )
                continue
            return url, response.text
        return None
