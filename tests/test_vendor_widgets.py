"""Tests for vendor_widgets.py parsers.

Pure-function tests -- no network, no Home Assistant test harness needed.
Fixtures are minimal HTML snippets confirmed against live pages during
development (see providers/citynews_ca.py history for the sources).
"""

import pytest

from custom_components.smart_fuel_price.providers import vendor_widgets
from custom_components.smart_fuel_price.providers.base import (
    cents_to_dollars,
    first_number,
)

# Confirmed live on toronto.citynews.ca/gas-prices/ (2026-09-27)
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

FORECAST_NO_MATCH_HTML = "<html><body>Nothing relevant here.</body></html>"

# Modelled on the State/Price/Trend widget from calgary.citynews.ca's
# GasBuddy embed (original screenshot, project history).
GASBUDDY_FALLING_HTML = """
<table id="APF_tbl">
  <tr>
    <td><span id="price126610">167.7</span></td>
    <td><img id="trend_img126610" src="https://df.gasbuddy.com/images/sm_trend_down.gif"></td>
  </tr>
</table>
"""

GASBUDDY_RISING_HTML = GASBUDDY_FALLING_HTML.replace(
    "sm_trend_down.gif", "sm_trend_up.gif"
)


class TestParseEnProForecast:
    def test_falling_price_computes_correct_current_and_tomorrow(self):
        result = vendor_widgets.parse_en_pro_forecast(FORECAST_FALLING_HTML)

        assert result is not None
        assert result["is_valid"] is True
        assert result["trend"] == "falling"
        assert result["is_dropping"] is True
        assert result["is_rising"] is False
        assert result["tomorrow_price"] == pytest.approx(1.819)
        # today = tomorrow + change = 181.9 + 7 = 188.9 cents = $1.889
        assert result["state"] == pytest.approx(1.889)
        assert "September 27, 2026" in result["effective_date_str"]

    def test_rising_price_computes_correct_current_and_tomorrow(self):
        result = vendor_widgets.parse_en_pro_forecast(FORECAST_RISING_HTML)

        assert result is not None
        assert result["trend"] == "rising"
        assert result["is_rising"] is True
        assert result["tomorrow_price"] == pytest.approx(1.909)
        # today = tomorrow - change = 190.9 - 4 = 186.9 cents = $1.869
        assert result["state"] == pytest.approx(1.869)

    def test_no_match_returns_none(self):
        assert vendor_widgets.parse_en_pro_forecast(FORECAST_NO_MATCH_HTML) is None


class TestParseGasbuddyReport:
    def test_falling_trend(self):
        result = vendor_widgets.parse_gasbuddy_report(GASBUDDY_FALLING_HTML)

        assert result is not None
        assert result["is_valid"] is True
        assert result["trend"] == "falling"
        assert result["is_dropping"] is True
        assert result["state"] == pytest.approx(1.677)
        assert result["tomorrow_price"] is None  # GasBuddy has no forecast

    def test_rising_trend(self):
        result = vendor_widgets.parse_gasbuddy_report(GASBUDDY_RISING_HTML)

        assert result is not None
        assert result["trend"] == "rising"
        assert result["is_rising"] is True

    def test_no_match_returns_none(self):
        assert vendor_widgets.parse_gasbuddy_report("<html></html>") is None


class TestBaseHelpers:
    def test_cents_to_dollars(self):
        assert cents_to_dollars(181.9) == pytest.approx(1.819)
        assert cents_to_dollars(None) is None

    def test_first_number(self):
        assert first_number("7 cent(s)") == 7.0
        assert first_number("181.9 cent(s)/litre") == 181.9
        assert first_number(None) is None
        assert first_number("no digits here") is None
