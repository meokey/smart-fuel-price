"""Tests for vendor_widgets.py parsers and base.py helpers.

Pure-function tests -- no network, no Home Assistant test harness needed.
Fixtures are minimal HTML snippets confirmed against live pages during
development.
"""

import pytest

from sfp_providers import vendor_widgets
from sfp_providers.base import cents_to_dollars, first_number, trend_fields

# Confirmed live on toronto.citynews.ca/gas-prices/ (2026-09-27).
# Deliberately line-wrapped mid-sentence to prove whitespace tolerance.
FORECAST_FALLING_HTML = """
<div class="gas-prices-section">
  <div class="data-box-change">
    <div class="up-arrow" style></div>
    <div class="down-arrow" style="display:block"></div>
    <div class="float-start">7 cent(s)</div>
  </div>
  <a href="http://www.en-pro.com/">En-Pro</a> tells CityNews that prices are
  expected to fall 7 cent(s) at 12:01am on September 27, 2026 to an average
  of 181.9 cent(s)/litre at local stations.
</div>
"""

FORECAST_RISING_HTML = """
<div class="gas-prices-section">
  En-Pro tells CityNews that prices are expected to rise 4 cents at 12:01am
  on October 1, 2026 to an average of 190.9 cents/litre at local stations.
</div>
"""

# Confirmed live on kitchener.citynews.ca/gas-prices/ (2026-09-27).
FORECAST_UNCHANGED_HTML = """
<div class="data-box-change">
  <div class="up-arrow" style=""></div>
  <div class="down-arrow" style=""></div>
  <div class="float-start">No Change</div>
</div>
<a href="http://www.en-pro.com/">En-Pro</a> tells CityNews that prices are
expected to remain unchanged at 12:01am on September 28, 2026 holding at an
average of 181.9 cent(s)/litre at local stations.
"""

FORECAST_NO_MATCH_HTML = "<html><body>Nothing relevant here.</body></html>"

# Modelled on calgary.citynews.ca/calgary-gas-prices/ (confirmed live
# 2026-10-09): the plain-GET page only carries the widget placeholder +
# script tag; the price arrives via a second GET to feed.gdf whose
# response is JavaScript writing the numbers into the DOM.
GASBUDDY_PAGE_HTML = """
<html><body>
<table><tr><td align="center" id="gasbuddy_12661"></td></tr></table>
<script src="https://df.gasbuddy.com/feed.gdf?k=KEY123&amp;ia=1&amp;i=12661"></script>
</body></html>
"""

GASBUDDY_FEED_JS_FALLING = (
    "document.getElementById('city126610').innerHTML='Calgary';"
    "document.getElementById('price126610').innerHTML='169.1';"
    "document.getElementById('trend_img126610').src="
    "'https://df.gasbuddy.com/images/sm_trend_down.gif';"
)

GASBUDDY_FEED_JS_RISING = GASBUDDY_FEED_JS_FALLING.replace(
    "sm_trend_down.gif", "sm_trend_up.gif"
)

GASBUDDY_PAGE_URL = "https://calgary.citynews.ca/calgary-gas-prices/"


class _FakeFeedResponse:
    def __init__(self, text):
        self.text = text


def _feed_get(mapping):
    """Fake provider._get: mapping of URL substring -> text or Exception."""
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        for key, value in mapping.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return _FakeFeedResponse(value)
        raise AssertionError(f"unexpected feed URL: {url}")

    get.calls = calls
    return get


class TestParseEnProForecast:
    def test_falling_price(self):
        result = vendor_widgets.parse_en_pro_forecast(FORECAST_FALLING_HTML)

        assert result is not None
        assert result["is_valid"] is True
        assert result["state"] == pytest.approx(-7.0)
        assert result["tomorrow_price"] == pytest.approx(181.9)
        assert result["current_price"] == pytest.approx(188.9)
        assert result["trend"] == "falling"
        assert result["is_dropping"] is True
        assert result["is_rising"] is False
        assert "September 27, 2026" in result["effective_date_str"]

    def test_rising_price(self):
        result = vendor_widgets.parse_en_pro_forecast(FORECAST_RISING_HTML)

        assert result is not None
        assert result["state"] == pytest.approx(4.0)
        assert result["tomorrow_price"] == pytest.approx(190.9)
        assert result["current_price"] == pytest.approx(186.9)
        assert result["trend"] == "rising"
        assert result["is_rising"] is True

    def test_unchanged_price(self):
        result = vendor_widgets.parse_en_pro_forecast(FORECAST_UNCHANGED_HTML)

        assert result is not None
        assert result["is_valid"] is True
        assert result["state"] == pytest.approx(0.0)
        assert result["tomorrow_price"] == pytest.approx(181.9)
        assert result["current_price"] == pytest.approx(181.9)
        assert result["trend"] == "stable"
        assert result["is_rising"] is False
        assert result["is_dropping"] is False
        assert "September 28, 2026" in result["effective_date_str"]

    def test_no_match_returns_none(self):
        assert vendor_widgets.parse_en_pro_forecast(FORECAST_NO_MATCH_HTML) is None


class TestParseGasbuddyReport:
    def test_falling_trend(self):
        get = _feed_get({"feed.gdf": GASBUDDY_FEED_JS_FALLING})
        result = vendor_widgets.parse_gasbuddy_report(
            GASBUDDY_PAGE_HTML, GASBUDDY_PAGE_URL, get
        )

        assert result is not None
        assert result["is_valid"] is True
        assert result["state"] == pytest.approx(169.1)
        assert result["current_price"] == pytest.approx(169.1)
        assert result["tomorrow_price"] is None  # average, not a forecast
        assert result["trend"] == "falling"
        assert result["is_dropping"] is True
        assert result["is_rising"] is False
        assert result["feed_city"] == "Calgary"
        # the browser-style second request carries the page as url=
        assert (
            "url=calgary.citynews.ca%2Fcalgary-gas-prices%2F" in get.calls[0]
        )

    def test_rising_trend(self):
        get = _feed_get({"feed.gdf": GASBUDDY_FEED_JS_RISING})
        result = vendor_widgets.parse_gasbuddy_report(
            GASBUDDY_PAGE_HTML, GASBUDDY_PAGE_URL, get
        )

        assert result is not None
        assert result["trend"] == "rising"
        assert result["is_rising"] is True

    def test_no_feed_tag_returns_none_without_network(self):
        get = _feed_get({})
        assert (
            vendor_widgets.parse_gasbuddy_report("<html></html>", GASBUDDY_PAGE_URL, get)
            is None
        )
        assert get.calls == []

    def test_feed_fetch_error_returns_none(self):
        get = _feed_get({"feed.gdf": RuntimeError("boom")})
        assert (
            vendor_widgets.parse_gasbuddy_report(
                GASBUDDY_PAGE_HTML, GASBUDDY_PAGE_URL, get
            )
            is None
        )

    def test_skips_feed_without_price(self):
        get = _feed_get(
            {
                "i=11111": "document.write('nothing here');",
                "i=12661": GASBUDDY_FEED_JS_FALLING,
            }
        )
        page = GASBUDDY_PAGE_HTML.replace("i=12661", "i=11111") + (
            '<script src="https://df.gasbuddy.com/feed.gdf?k=KEY123&ia=1&i=12661">'
            "</script>"
        )
        result = vendor_widgets.parse_gasbuddy_report(page, GASBUDDY_PAGE_URL, get)

        assert result is not None
        assert result["state"] == pytest.approx(169.1)
        assert len(get.calls) == 2


class TestBaseHelpers:
    def test_cents_to_dollars(self):
        assert cents_to_dollars(181.9) == pytest.approx(1.819)
        assert cents_to_dollars(None) is None

    def test_first_number(self):
        assert first_number("7 cent(s)") == 7.0
        assert first_number("181.9 cent(s)/litre") == 181.9
        assert first_number(None) is None
        assert first_number("no digits here") is None

    @pytest.mark.parametrize(
        "change, trend, rising, dropping",
        [
            (4.0, "rising", True, False),
            (-7.0, "falling", False, True),
            (0.0, "stable", False, False),
            (None, "unknown", False, False),
        ],
    )
    def test_trend_fields(self, change, trend, rising, dropping):
        assert trend_fields(change) == {
            "trend": trend,
            "is_rising": rising,
            "is_dropping": dropping,
        }


def test_has_gasbuddy_widget():
    from sfp_providers import vendor_widgets

    page = '<script src="https://df.gasbuddy.com/feed.gdf?k=abc&i=12661"></script>'
    assert vendor_widgets.has_gasbuddy_widget(page) is True
    assert vendor_widgets.has_gasbuddy_widget("<html>no widget here</html>") is False
