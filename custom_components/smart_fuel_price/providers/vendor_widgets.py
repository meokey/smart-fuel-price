"""Shared parsers for third-party price widgets embedded across many
Canadian broadcaster/news sites.

These are NOT specific to CityNews -- both the En-Pro/GasWizard forecast
box and the GasBuddy report widget are commonly white-labelled onto
multiple regional news sites' "Gas Prices" pages. Keeping the parsing
logic here (rather than duplicated per-provider) means a second provider
plugin embedding either widget can reuse it directly.

Each function takes raw page HTML and returns a dict matching
BaseFuelPriceProvider.fetch_data()'s schema, or None if the expected
markup wasn't found. All prices are cents per litre (matching the
sensor's ¢/L unit):

    state           signed change, tomorrow - current (e.g. -7.0, 0.0, 4.0)
    tomorrow_price  forecast average
    current_price   today's average
    trend           "rising" | "falling" | "stable" | "unknown"
"""

import re
from typing import Any

from .base import trend_fields

_RISE_WORDS = {"rise", "increase", "climb", "jump"}
_FALL_WORDS = {"fall", "decrease", "drop", "dip"}
_DIRECTION_ALT = "|".join(sorted(_RISE_WORDS | _FALL_WORDS, key=len, reverse=True))
_CENT_UNIT = r"cent(?:\(s\))?s?"  # matches "cent", "cent(s)" or "cents"

# Whitespace-tolerant: real pages (or line-wrapped fixtures) may break the
# sentence across lines.
_LEAD = r"tells\s+CityNews\s+that\s+prices\s+are\s+expected\s+to\s+"
_AT_TIME_ON_DATE = (
    r"\s+at\s+(?P<time>[\d:apm]+)\s+on\s+"
    r"(?P<date>[A-Za-z]+\s+\d{1,2},?\s+\d{4})"
)
_TO_AVERAGE = (
    r".*?average\s+of\s+(?P<avg>[\d.]+)\s*" + _CENT_UNIT + r"\s*/\s*litre"
)

# "...expected to fall 7 cent(s) at 12:01am on September 27, 2026 to an
#  average of 181.9 cent(s)/litre at local stations."
_EN_PRO_CHANGE_RE = re.compile(
    _LEAD
    + r"(?P<direction>"
    + _DIRECTION_ALT
    + r")\s+(?P<change>[\d.]+)\s*"
    + _CENT_UNIT
    + _AT_TIME_ON_DATE
    + _TO_AVERAGE,
    re.IGNORECASE | re.DOTALL,
)

# "...expected to remain unchanged at 12:01am on September 28, 2026 holding
#  at an average of 181.9 cent(s)/litre at local stations." (seen on Kitchener)
_EN_PRO_UNCHANGED_RE = re.compile(
    _LEAD
    + r"(?:remain|stay)\s+(?:unchanged|the\s+same)"
    + _AT_TIME_ON_DATE
    + _TO_AVERAGE,
    re.IGNORECASE | re.DOTALL,
)

_GASBUDDY_PRICE_RE = re.compile(r'<span[^>]+id="price\d+"[^>]*>\s*([\d.]+)\s*</span>')
_GASBUDDY_TREND_IMG_RE = re.compile(
    r'<img[^>]+id="trend_img\d+"[^>]+src="([^"]+)"', re.IGNORECASE
)


def _forecast_result(
    current_cents: float, tomorrow_cents: float, effective_date_str: str
) -> dict[str, Any]:
    change_cents = round(tomorrow_cents - current_cents, 1)
    return {
        "state": change_cents,
        "tomorrow_price": tomorrow_cents,
        "current_price": current_cents,
        "effective_date_str": effective_date_str,
        "is_valid": True,
        **trend_fields(change_cents),
    }


def parse_en_pro_forecast(page_html: str) -> dict[str, Any] | None:
    """Parse the En-Pro/GasWizard-style forecast sentence.

    Confirmed live on citynews.ca's Toronto and Ottawa pages (rise/fall
    wording) and Kitchener (the "remain unchanged" wording). The sentence
    names CityNews specifically -- generalise the regexes if this widget
    shows up on a non-CityNews site.
    """
    match = _EN_PRO_CHANGE_RE.search(page_html)
    if match:
        change_cents = float(match.group("change"))
        if match.group("direction").lower() in _FALL_WORDS:
            change_cents = -change_cents
        tomorrow_cents = float(match.group("avg"))
        # "expected to fall 7 ... to an average of X" => X is tomorrow's
        # price and today's is X + 7 (mirrored for a rise).
        current_cents = round(tomorrow_cents - change_cents, 1)
    else:
        match = _EN_PRO_UNCHANGED_RE.search(page_html)
        if not match:
            return None
        tomorrow_cents = float(match.group("avg"))
        current_cents = tomorrow_cents

    effective_date_str = f"{match.group('date').strip()} {match.group('time').strip()}"
    return _forecast_result(current_cents, tomorrow_cents, effective_date_str)


def parse_gasbuddy_report(report_html: str) -> dict[str, Any] | None:
    """Parse GasBuddy's State/Price/Trend summary widget.

    STATUS: unverified/parked (see citynews_ca.py, Calgary). The summary
    widget gives the current price and a trend arrow but no change size,
    so `state` stays None until the "Historical prices" table (Today vs
    Yesterday) is parsed as well.
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
        "state": None,
        "tomorrow_price": None,
        "current_price": current_cents,
        "trend": trend,
        "effective_date_str": "N/A",
        "is_valid": True,
        "is_rising": is_rising,
        "is_dropping": is_dropping,
    }
