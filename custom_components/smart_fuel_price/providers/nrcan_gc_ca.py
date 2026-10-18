"""Natural Resources Canada weekly average retail price provider.

NRC publishes weekly average retail fuel prices for ~70 Canadian cities::

    https://www2.nrcan.gc.ca/eneene/sources/pripri/prices_bycity_e.cfm
        ?priceYear=YYYY&productID=1&locationID=NN&frequency=W

``productID=1`` is Regular Gasoline. Each page carries one plain HTML
table -- ``Week Ending | Price | Taxes | Marketing Margin | Refining
Margin`` -- with one row per week (week-ending dates are Tuesdays),
prices in cents per litre including taxes. A machine-friendly XLS
download and an RSS feed are also offered on the page. No JavaScript,
no login, no bot-wall: a plain GET is enough.

This is a REFERENCE ANCHOR, not a forecast (#59): it tells the user
whether today's pump price is high or low against the official weekly
average. The data is inherently lagged, so:

* ``supports_forecast`` is False -- no Buy-now sensor is created;
* ``allow_stale_on_failure`` is True -- last week's average still beats
  no reference during an outage;
* ``scan_interval`` is 7 days -- the source moves weekly.

Row selection: the table can already contain a row for the *upcoming*
Tuesday (a partial-week average -- NRC averages "price data available").
The sensor must never present a partial week as the reference, so the
provider picks the latest row whose week-ending date is strictly before
today (America/Toronto). Around New Year the latest completed week may
live on the previous year's page, which is fetched as a fallback.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

_TORONTO_TZ = ZoneInfo("America/Toronto")

_BASE_URL = (
    "https://www2.nrcan.gc.ca/eneene/sources/pripri/prices_bycity_e.cfm"
)
# City index page: carries the "View prices for CANADA or one of the
# cities below" link list used by discover_cities().
_INDEX_URL = (
    "https://www2.nrcan.gc.ca/eneene/sources/pripri/"
    "prices_byfuel_e.cfm?locationName=Toronto"
)

# Static city slug -> NRC locationID map, harvested from NRC's own city
# index page (prices_byfuel_e.cfm, Oct 2026: every link carries its
# locationID). Toronto=17 and Winnipeg=15 were additionally verified
# against the bycity weekly-table page titles. Slugs follow the
# integration's convention: lowercase ASCII, spaces become hyphens,
# punctuation dropped ("Sault Ste Marie" -> "sault-ste-marie",
# "Trois-Rivières" -> "trois-rivieres").
_CITY_LOCATION_IDS: dict[str, int] = {
    "abbotsford": 90,
    "barrie": 91,
    "bathurst": 36,
    "brandon": 16,
    "brantford": 92,
    "calgary": 8,
    "campbellton": 82,
    "charlottetown": 43,
    "chicoutimi": 32,
    "corner-brook": 46,
    "drummondville": 69,
    "edmonton": 10,
    "edmundston": 37,
    "fort-st-john": 70,
    "fredericton": 34,
    "gander": 45,
    "gaspe": 31,
    "gatineau": 98,
    "grand-falls": 99,
    "grande-prairie": 100,
    "guelph": 93,
    "halifax": 39,
    "hamilton": 26,
    "kamloops": 5,
    "kelowna": 6,
    "kentville": 71,
    "kingston": 72,
    "kitchener": 94,
    "labrador-city": 73,
    "lethbridge": 11,
    "lloydminster": 74,
    "london": 20,
    "miramichi": 38,
    "moncton": 35,
    "montreal": 28,
    "moose-jaw": 97,
    "new-glasgow": 75,
    "north-bay": 24,
    "oshawa": 95,
    "ottawa": 18,
    "peterborough": 76,
    "prince-albert": 14,
    "prince-george": 4,
    "quebec": 29,
    "red-deer": 9,
    "regina": 12,
    "rimouski": 77,
    "saint-john": 33,
    "sarnia": 58,
    "saskatoon": 13,
    "sault-ste-marie": 22,
    "sherbrooke": 30,
    "st-catharines": 27,
    "st-johns": 44,
    "sudbury": 21,
    "sussex": 78,
    "sydney": 40,
    "thunder-bay": 23,
    "timmins": 25,
    "toronto": 17,
    "trois-rivieres": 79,
    "truro": 42,
    "val-dor": 80,
    "vancouver": 2,
    "victoria": 3,
    "whitehorse": 1,
    "windsor": 19,
    "winnipeg": 15,
    "woodstock": 81,
    "yarmouth": 41,
    "yellowknife": 7,
}

# Discovered (index-page) slug -> locationID pairs, populated by
# discover_cities(). Lets the config flow offer cities added by NRC
# after this map was curated, without a code change.
_DISCOVERED_IDS: dict[str, int] = {}

# <tr><td>2026-10-13</td><td>184.6</td><td>30.2</td><td>13.3</td><td>59.3</td></tr>
# The three component columns are optional -- the price is what matters.
_WEEK_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\s*(20\d{2}-\d{2}-\d{2})\s*</td>"
    r"\s*<td[^>]*>\s*([\d.]+)\s*</td>"
    r"(?:\s*<td[^>]*>\s*([\d.]+)\s*</td>"
    r"\s*<td[^>]*>\s*([\d.]+)\s*</td>"
    r"\s*<td[^>]*>\s*([\d.]+)\s*</td>)?",
    re.IGNORECASE,
)

# City links on the index page, e.g.
# <a href="prices_byfuel_e.cfm?locationID=17&...">Toronto</a>
# (both locationID= and locationName= forms are accepted).
_CITY_LINK_RE = re.compile(
    r'href="[^"]*prices_by\w+_e\.cfm\?[^"]*?(?:locationID=(\d+)|locationName=([^"&]+))[^"]*"[^>]*>\s*([^<]+?)\s*<',
    re.IGNORECASE,
)


def _slugify(name: str) -> str:
    import unicodedata

    slug = name.lower().strip()
    # Strip accents ("Trois-Rivières" -> "trois-rivieres").
    slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode()
    slug = re.sub(r"['.]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def _parse_weekly_rows(html: str) -> list[tuple[str, float, dict[str, float]]]:
    """Extract (week_ending, price, components) rows from a bycity page."""
    rows = []
    for match in _WEEK_ROW_RE.finditer(html):
        week_ending, price = match.group(1), match.group(2)
        try:
            price_f = float(price)
        except ValueError:
            continue
        if price_f <= 0:
            continue
        components: dict[str, float] = {}
        if match.group(3) is not None:
            try:
                components = {
                    "taxes": float(match.group(3)),
                    "marketing_margin": float(match.group(4)),
                    "refining_margin": float(match.group(5)),
                }
            except (ValueError, TypeError):
                components = {}
        rows.append((week_ending, price_f, components))
    # Deduplicate (the page can repeat the table) and sort by date.
    seen: dict[str, tuple[float, dict[str, float]]] = {}
    for week_ending, price_f, components in rows:
        seen.setdefault(week_ending, (price_f, components))
    return sorted(
        ((d, p, c) for d, (p, c) in seen.items()), key=lambda r: r[0]
    )


class NrcanGcCaProvider(BaseFuelPriceProvider):
    """Provider for NRC's weekly average retail prices (nrcan.gc.ca)."""

    # www2.nrcan.gc.ca serves no robots.txt (fail-open per the global
    # rule); the 7-day poll interval keeps us far under any limit.
    _ROBOTS_TXT_URL = "https://www2.nrcan.gc.ca/robots.txt"
    _ROBOTS_CHECK_URL = (
        "https://www2.nrcan.gc.ca/eneene/sources/pripri/"
        "prices_bycity_e.cfm?priceYear=2026&productID=1"
        "&locationID=17&frequency=W"
    )

    @property
    def name(self) -> str:
        return "Natural Resources Canada"

    @property
    def sensor_name(self) -> str:
        return "NRC Weekly Average"

    @property
    def scan_interval(self) -> timedelta:
        # The source moves weekly; polling faster would only re-read the
        # same table.
        return timedelta(days=7)

    @property
    def supports_forecast(self) -> bool:
        # A lagged weekly average is a reference anchor, not a forecast --
        # no Buy-now sensor.
        return False

    @property
    def allow_stale_on_failure(self) -> bool:
        # Last week's official average still answers "is today's price
        # high or low?" during an outage.
        return True

    @classmethod
    def get_supported_cities(cls) -> list[str]:
        return sorted(_CITY_LOCATION_IDS)

    @classmethod
    def verified_cities(cls) -> frozenset[str]:
        return frozenset(_CITY_LOCATION_IDS)

    @classmethod
    def city_has_prices(
        cls, city: str, session: requests.Session | None = None
    ) -> bool:
        # NRC's index only lists cities that have a weekly table, so
        # membership in the known map is the check -- no network needed.
        return city in _CITY_LOCATION_IDS or city in _DISCOVERED_IDS

    @classmethod
    def _location_id(cls, city: str) -> int | None:
        return _DISCOVERED_IDS.get(city, _CITY_LOCATION_IDS.get(city))

    @classmethod
    def discover_cities(cls) -> dict[str, str] | None:
        """Best-effort live city list from NRC's city index page.

        One plain GET; the index only links cities that have data.
        Discovered locationIDs are stashed on the class so provider
        instances created later can fetch without a code change.
        """
        try:
            session = cls._build_session()
            response = session.get(_INDEX_URL, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as err:
            _LOGGER.warning(
                "NRC city discovery failed, using static list: %s", err
            )
            return None

        found: dict[str, str] = {}
        for loc_id, loc_name, label in _CITY_LINK_RE.findall(response.text):
            label = label.strip()
            if not label or label.upper() == "CANADA":
                continue
            slug = _slugify(label)
            found[slug] = label
            if loc_id:
                _DISCOVERED_IDS.setdefault(slug, int(loc_id))
        if not found:
            _LOGGER.warning(
                "NRC city discovery found no city links; using static list."
            )
            return None
        return found

    @property
    def source_url(self) -> str | None:
        loc_id = self._location_id(self.city)
        if loc_id is None:
            return None
        year = datetime.now(_TORONTO_TZ).year
        return (
            f"{_BASE_URL}?priceYear={year}&productID=1"
            f"&locationID={loc_id}&frequency=W"
        )

    def _table_url(self, location_id: int, year: int) -> str:
        return (
            f"{_BASE_URL}?priceYear={year}&productID=1"
            f"&locationID={location_id}&frequency=W"
        )

    def _parse_data(self) -> dict[str, Any]:
        location_id = self._location_id(self.city)
        if location_id is None:
            _LOGGER.error(
                "[%s] No NRC locationID for city '%s'.",
                self.name,
                self.city,
            )
            return {"city": self.city, "is_valid": False}

        today = datetime.now(_TORONTO_TZ).date()
        year = today.year
        # Latest completed week first; around New Year it may live on
        # last year's page.
        for table_year in (year, year - 1):
            try:
                response = self._get(
                    self._table_url(location_id, table_year)
                )
            except requests.exceptions.RequestException as err:
                _LOGGER.warning(
                    "[%s] Could not fetch weekly table for '%s' (%d): %s",
                    self.name,
                    self.city,
                    table_year,
                    err,
                )
                continue
            rows = _parse_weekly_rows(response.text)
            # Never present a partial (future-dated) week as the reference.
            completed = [r for r in rows if r[0] < today.isoformat()]
            if not completed:
                continue
            week_ending, price, components = completed[-1]
            _LOGGER.debug(
                "[%s] %s: weekly average %.1f ¢/L (week ending %s)",
                self.name,
                self.city,
                price,
                week_ending,
            )
            return {
                "city": self.city,
                "current_price": round(price, 1),
                "week_ending": week_ending,
                "price_taxes": components.get("taxes"),
                "price_marketing_margin": components.get(
                    "marketing_margin"
                ),
                "price_refining_margin": components.get(
                    "refining_margin"
                ),
                "is_valid": True,
            }

        _LOGGER.warning(
            "[%s] No completed weekly row found for '%s'.",
            self.name,
            self.city,
        )
        return {"city": self.city, "is_valid": False}
