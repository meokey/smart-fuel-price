"""Affordable Energy Canada (Gas Wizard) Provider.

gaswizard.ca is Dan McTeague / Canadians for Affordable Energy's own site --
the PRIMARY source for the same next-day forecast data that En-Pro licenses
out to CityNews (see vendor_widgets.py / citynews_ca.py). It is a plain
server-rendered WordPress site (Astra theme); no JS rendering is involved.

Each city page (https://www.gaswizard.ca/<city>, which redirects to
https://gaswizard.ca/gas-prices/<city>/) contains a rolling, newest-first
list of daily "Regular" price entries:

    <ul class="single-city-prices ">
      <li>
        <span class="daytext">Monday</span> -
        <span class="datetext">Sep 28, 2026</span>
        ... <div class="fueltitle">Regular</div>
        <div class="fuelprice"><span class="fuel-price-value">181.9</span> ...
      </li>
      <li> ... previous day ... </li>
      <li> ... "Current Average Price" (no daytext -- skipped) ... </li>
    </ul>

Design notes:
  * Each <li> is parsed on its own. The first version tied each entry to a
    following <div class="price-direction pd-...">; on a "no change" day
    that div is absent (the page shows "---"), so the regex ran on into
    the next entry and swallowed it. Direction markup isn't needed at all:
    trend comes from comparing the two prices.
  * Order verified 2026-09-27 (8:53 pm): entry[0] = Monday Sep 28
    (tomorrow's prediction); entry[1] = Sunday Sep 27, whose price equals
    the page's own "Current Average Price". So entry[1] -> current_price;
    state is their difference.
  * 2026-10-06: the site sometimes hasn't published tomorrow's prediction
    yet -- then entry[0] is *today*, not tomorrow. The entry date is now
    verified against tomorrow (America/Toronto); if it doesn't match, the
    forecast is reported invalid instead of a misleading 0.0 change.
  * 2026-10-06: entries are now matched by calendar date, not page position,
    and today's price is always reported when the site lists today -- even
    while tomorrow's forecast is still missing.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .base import BaseFuelPriceProvider, trend_fields

_LOGGER = logging.getLogger(__name__)

# Only "toronto" and "gta" have been live-verified; the rest follow the
# same URL pattern by inference (all appear in the site's own city list).
CITY_MAP: dict[str, str] = {
    "toronto": "toronto",
    "mississauga": "mississauga",
    "vancouver": "vancouver",
    "calgary": "calgary",
    "ottawa": "ottawa",
    "montreal": "montreal",
    "gta": "gta",
}

_PRICE_LIST_RE = re.compile(
    r'<ul class="single-city-prices[^"]*">(?P<body>.*?)</ul>', re.DOTALL
)
_LI_RE = re.compile(r"<li\b[^>]*>(?P<body>.*?)</li>", re.DOTALL)
_ENTRY_RE = re.compile(
    r'<span class="daytext">(?P<day>[^<]+)</span>\s*-\s*'
    r'<span class="datetext">(?P<date>[^<]+)</span>.*?'
    r'<div class="fueltitle">Regular</div>\s*'
    r'<div class="fuelprice">\s*'
    r'<span class="fuel-price-value">(?P<price>[\d.]+)</span>',
    re.DOTALL,
)


def _extract_entries(page_html: str) -> list[re.Match[str]]:
    """Return one match per <li> holding a dated 'Regular' price, in page order.

    List items without a day/date/Regular price (e.g. "Current Average
    Price") simply don't match and are skipped.
    """
    price_list = _PRICE_LIST_RE.search(page_html)
    if not price_list:
        return []
    entries = []
    for li in _LI_RE.finditer(price_list.group("body")):
        entry = _ENTRY_RE.search(li.group("body"))
        if entry:
            entries.append(entry)
    return entries


# Gas Wizard publishes on a Toronto schedule; the forecast contract is
# anchored to America/Toronto regardless of the HA host's timezone.
_SITE_TZ = ZoneInfo("America/Toronto")


def _parse_entry_date(date_str: str) -> "datetime.date":
    """Parse a '<span class="datetext">' value like 'Oct 6, 2026'."""
    return datetime.strptime(date_str.strip(), "%b %d, %Y").date()


def _tomorrow_in_site_tz() -> "datetime.date":
    return (datetime.now(_SITE_TZ) + timedelta(days=1)).date()


def _today_in_site_tz() -> "datetime.date":
    return datetime.now(_SITE_TZ).date()


class AffordableEnergyCaProvider(BaseFuelPriceProvider):
    """Provider for Gas Wizard (gaswizard.ca)."""

    BASE_URL = "https://www.gaswizard.ca"

    @property
    def name(self) -> str:
        return "Affordable Energy (Gas Wizard)"

    @classmethod
    def get_supported_cities(cls) -> list[str]:
        return list(CITY_MAP.keys())

    @property
    def source_url(self) -> str | None:
        slug = CITY_MAP.get(self.city, CITY_MAP["toronto"])
        return f"{self.BASE_URL}/{slug}"

    def _parse_data(self) -> dict[str, Any]:
        slug = CITY_MAP.get(self.city)
        if not slug:
            _LOGGER.warning(
                "[%s] City '%s' is not in the known map; falling back to 'toronto'.",
                self.name,
                self.city,
            )
            slug = CITY_MAP["toronto"]

        url = f"{self.BASE_URL}/{slug}"
        page_html = self._get(url).text

        entries = _extract_entries(page_html)
        if not entries:
            _LOGGER.warning(
                "[%s] Found no dated 'Regular' price entries for '%s' -- "
                "page layout may have changed.",
                self.name,
                slug,
            )
            return {"city": slug, "is_valid": False}

        # Match entries by calendar date, not page position: the site lists
        # only 2 entries and the newest is not always tomorrow's forecast
        # (it isn't published yet for much of the day).
        dated: list[tuple[datetime.date, re.Match]] = []
        for entry in entries:
            try:
                dated.append((_parse_entry_date(entry.group("date")), entry))
            except ValueError:
                _LOGGER.warning(
                    "[%s] Could not parse entry date %r for '%s' -- page layout "
                    "may have changed.",
                    self.name,
                    entry.group("date"),
                    slug,
                )

        today = _today_in_site_tz()
        tomorrow = _tomorrow_in_site_tz()
        today_entry = next((e for d, e in dated if d == today), None)
        tomorrow_entry = next((e for d, e in dated if d == tomorrow), None)

        # Today's price is known whenever the site lists today -- even while
        # tomorrow's forecast is still missing.
        current_cents = float(today_entry.group("price")) if today_entry else None

        if tomorrow_entry is None:
            # Routine, expected transient state: Gas Wizard publishes
            # tomorrow's forecast on its own schedule (usually by the
            # evening). Info-level only -- a warning here would surface as
            # an error in the HA log UI and needlessly alarm the user.
            # The forecast sensors report unknown; today's price is still
            # reported since it is known.
            newest = dated[0][0].isoformat() if dated else "none"
            _LOGGER.info(
                "[%s] No entry dated %s for '%s' (newest is %s) -- tomorrow's "
                "forecast is not published yet.",
                self.name,
                tomorrow.isoformat(),
                slug,
                newest,
            )
            return {
                "city": slug,
                "is_valid": False,
                "state": None,
                "tomorrow_price": None,
                "current_price": current_cents,
            }

        tomorrow_cents = float(tomorrow_entry.group("price"))
        change_cents = (
            round(tomorrow_cents - current_cents, 1)
            if current_cents is not None
            else None
        )

        return {
            "state": change_cents,
            "tomorrow_price": tomorrow_cents,
            "current_price": current_cents,
            "effective_date_str": f"{tomorrow_entry.group('day').strip()} {tomorrow_entry.group('date').strip()}",
            "is_valid": True,
            "city": slug,
            **trend_fields(change_cents),
        }
