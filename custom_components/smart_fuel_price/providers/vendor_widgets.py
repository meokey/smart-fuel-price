"""Shared parsers for third-party price widgets embedded across many
Canadian broadcaster/news sites.

These are NOT specific to CityNews -- both the En-Pro/GasWizard forecast
box and the GasBuddy report widget are commonly white-labelled onto
multiple regional news sites' "Gas Prices" pages. Keeping the parsing
logic here (rather than duplicated per-provider) means a second provider
plugin embedding either widget can reuse it directly.

Each function takes raw page HTML and returns a dict matching
BaseFuelPriceProvider.fetch_data()'s schema (state/tomorrow_price/trend/
effective_date_str/is_valid/is_rising/is_dropping), or None if the
expected markup wasn't found.
"""

import re
from typing import Any

from .base import cents_to_dollars

_RISE_WORDS = {"rise", "increase", "climb", "jump"}
_FALL_WORDS = {"fall", "decrease", "drop", "dip"}
_DIRECTION_ALT = "|".join(sorted(_RISE_WORDS | _FALL_WORDS, key=len, reverse=True))
_CENT_UNIT = r"cent(?:\(s\))?s?"  # matches "cent", "cent(s)" or "cents"

_EN_PRO_SENTENCE_RE = re.compile(
    r"tells CityNews that prices are expected to\s+(?P<direction>"
    + _DIRECTION_ALT
    + r")\s+(?P<change>[\d.]+)\s*"
    + _CENT_UNIT
    + r"\s+at\s+(?P<time>[\d:apm]+)\s+on\s+(?P<date>[A-Za-z]+\s+\d{1,2},?\s+\d{4})"
    + r".*?average of\s+(?P<avg>[\d.]+)\s*"
    + _CENT_UNIT
    + r"/litre",
    re.IGNORECASE | re.DOTALL,
)

_GASBUDDY_PRICE_RE = re.compile(r'<span[^>]+id="price\d+"[^>]*>\s*([\d.]+)\s*</span>')
_GASBUDDY_TREND_IMG_RE = re.compile(
    r'<img[^>]+id="trend_img\d+"[^>]+src="([^"]+)"', re.IGNORECASE
)


def parse_en_pro_forecast(page_html: str) -> dict[str, Any] | None:
    """Parse the En-Pro/GasWizard-style forecast sentence.

    Confirmed live on citynews.ca's Toronto, Ottawa and Kitchener pages,
    e.g.: "En-Pro tells CityNews that prices are expected to fall 7
    cent(s) at 12:01am on September 27, 2026 to an average of 181.9
    cent(s)/litre at local stations." The site name in the sentence
    ("tells CityNews") is currently hardcoded to CityNews specifically --
    generalise the regex if/when this shows up on a non-CityNews site.
    """
    match = _EN_PRO_SENTENCE_RE.search(page_html)
    if not match:
        return None

    direction_word = match.group("direction").lower()
    change_cents = float(match.group("change"))
    tomorrow_cents = float(match.group("avg"))
    effective_date_str = f"{match.group('date').strip()} {match.group('time').strip()}"

    is_rising = direction_word in _RISE_WORDS
    is_dropping = direction_word in _FALL_WORDS
    trend = "rising" if is_rising else "falling" if is_dropping else "unknown"

    # "prices are expected to fall 7 cents ... to an average of X" means X
    # is TOMORROW's price and today's is X + 7 (mirrored for a rise).
    current_cents = (
        tomorrow_cents - change_cents
        if is_rising
        else tomorrow_cents + change_cents
        if is_dropping
        else tomorrow_cents
    )

    return {
        "state": cents_to_dollars(current_cents),
        "tomorrow_price": cents_to_dollars(tomorrow_cents),
        "trend": trend,
        "effective_date_str": effective_date_str,
        "is_valid": True,
        "is_rising": is_rising,
        "is_dropping": is_dropping,
    }


def parse_gasbuddy_report(report_html: str) -> dict[str, Any] | None:
    """Parse GasBuddy's State/Price/Trend summary widget.

    STATUS: unverified/parked. The page-embed chain that reaches this
    markup hasn't been pinned down for Calgary yet (see citynews_ca.py).
    This function is ready to go once we have a confirmed HTML sample.
    """
    price_match = _GASBUDDY_PRICE_RE.search(report_html)
    if not price_match:
        return None

    current_cents = float(price_match.group(1))

    trend_img_match = _GASBUDDY_TREND_IMG_RE.search(report_html)
    trend_src = trend_img_match.group(1).lower() if trend_img_match else ""
    is_dropping = "down" in trend_src
    is_rising = "up" in trend_src
    trend = "rising" if is_rising else "falling" if is_dropping else "unknown"

    return {
        "state": cents_to_dollars(current_cents),
        "tomorrow_price": None,
        "trend": trend,
        "effective_date_str": "N/A",
        "is_valid": True,
        "is_rising": is_rising,
        "is_dropping": is_dropping,
    }
