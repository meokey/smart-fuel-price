"""Affordable Energy Canada (Gas Wizard) Provider.

gaswizard.ca is Dan McTeague / Canadians for Affordable Energy's own site --
the PRIMARY source for the same next-day forecast data that En-Pro licenses
out to CityNews (see vendor_widgets.py / citynews_ca.py). Confirmed as a
plain server-rendered WordPress site (Astra theme) via direct GET -- no JS
rendering involved, unlike Calgary's GasBuddy embed.

Each city page (https://www.gaswizard.ca/<city>) shows a rolling,
newest-first list of daily "Regular" price entries:

    <ul class="single-city-prices ">
      <li>
        <span class="daytext">Saturday</span> -
        <span class="datetext">Sep 26, 2026</span>
        ...
        <div class="fueltitle">Regular</div>
        <div class="fuelprice">
          <span class="fuel-price-value">188.9</span>
          <div class="price-direction pd-up">
            <span class="price-text">+1&#162;</span>
          </div>
        </div>
      </li>
      <li> ... previous day (e.g. Friday, 187.9) ... </li>
      ...
    </ul>

Consecutive entries' prices are directly consistent with the shown delta
(entry[0].price - delta == entry[1].price), so both values can be read
straight off the page -- no arithmetic needed, unlike CityNews's sentence.

ASSUMPTION (not explicitly labelled by the site): list position is newest
first, so entry[0] = latest/upcoming prediction (tomorrow_price), entry[1]
= prior confirmed price (state). Revisit if a future capture contradicts
this ordering.
"""

import logging
import re
from typing import Any, Dict, List

from .base import BaseFuelPriceProvider, cents_to_dollars

_LOGGER = logging.getLogger(__name__)

# Only "toronto" has been live-verified; the rest follow the same URL
# pattern by inference from the site's uniform per-city page structure.
CITY_MAP: Dict[str, str] = {
    "toronto": "toronto",
    "mississauga": "mississauga",
    "vancouver": "vancouver",
    "calgary": "calgary",
    "ottawa": "ottawa",
    "montreal": "montreal",
}

_ENTRY_RE = re.compile(
    r'<span class="daytext">(?P<day>[^<]+)</span>\s*-\s*'
    r'<span class="datetext">(?P<date>[^<]+)</span>.*?'
    r'<div class="fueltitle">Regular</div>\s*'
    r'<div class="fuelprice">\s*'
    r'<span class="fuel-price-value">(?P<price>[\d.]+)</span>.*?'
    r'<div class="price-direction (?P<direction>pd-up|pd-down|pd-flat)">',
    re.DOTALL,
)


class AffordableEnergyCaProvider(BaseFuelPriceProvider):
    """Provider for Gas Wizard (gaswizard.ca)."""

    BASE_URL = "https://www.gaswizard.ca"

    @property
    def name(self) -> str:
        return "Affordable Energy (Gas Wizard)"

    @classmethod
    def get_supported_cities(cls) -> List[str]:
        return list(CITY_MAP.keys())

    def _parse_data(self) -> Dict[str, Any]:
        slug = CITY_MAP.get(self.city)
        if not slug:
            _LOGGER.warning(
                "[%s] City '%s' is not in the known map; falling back to 'toronto'.",
                self.name, self.city,
            )
            slug = CITY_MAP["toronto"]

        url = f"{self.BASE_URL}/{slug}"
        page_html = self._get(url).text

        matches = list(_ENTRY_RE.finditer(page_html))
        if len(matches) < 2:
            _LOGGER.warning(
                "[%s] Found %d 'Regular' price entries for '%s' (need at "
                "least 2) -- page layout may have changed.",
                self.name, len(matches), slug,
            )
            return {"city": slug, "is_valid": False}

        latest, prior = matches[0], matches[1]
        tomorrow_cents = float(latest.group("price"))
        current_cents = float(prior.group("price"))

        is_rising = tomorrow_cents > current_cents
        is_dropping = tomorrow_cents < current_cents
        trend = "rising" if is_rising else "falling" if is_dropping else "unknown"

        return {
            "state": cents_to_dollars(current_cents),
            "tomorrow_price": cents_to_dollars(tomorrow_cents),
            "trend": trend,
            "effective_date_str": f"{latest.group('day').strip()} {latest.group('date').strip()}",
            "is_valid": True,
            "is_rising": is_rising,
            "is_dropping": is_dropping,
            "city": slug,
        }
