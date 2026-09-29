"""Offline end-to-end tests: provider.fetch_data() against canned HTML.

A fake requests-style session is injected through the provider's
`session` constructor argument, so no network access is needed.
"""

import pytest
import requests

from sfp_providers.affordableenergy_ca import AffordableEnergyCaProvider
from sfp_providers.citynews_ca import CityNewsCaProvider
from sfp_providers.gasbuddy_ca import GasBuddyStationProvider

class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))


class FakeSession:
    """Maps URL -> HTML; any other URL is a 404."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if url in self.pages:
            return FakeResponse(self.pages[url])
        return FakeResponse("", status_code=404)


# Minimal fixture modelled on the live gaswizard.ca/toronto markup.
GASWIZARD_TORONTO_HTML = """
<ul class="single-city-prices "><h2 class="entry-title">Toronto</h2>
<li><div><span class="daytext">Saturday</span> - <span class="datetext">Sep 26, 2026</span></div>
<div class="fueltype"><div class="fueltitle">Regular</div>
<div class="fuelprice"><span class="fuel-price-value">188.9</span>
<div class="price-direction pd-up"><span class="price-text">+1&#162;</span></div></div></div></li>
<li><div><span class="daytext">Friday</span> - <span class="datetext">Sep 25, 2026</span></div>
<div class="fueltype"><div class="fueltitle">Regular</div>
<div class="fuelprice"><span class="fuel-price-value">187.9</span>
<div class="price-direction pd-up"><span class="price-text">+2&#162;</span></div></div></div></li>
</ul>
"""

CITYNEWS_TORONTO_HTML = (
    '<a href="http://www.en-pro.com/">En-Pro</a> tells CityNews that prices '
    "are expected to fall 7 cent(s) at 12:01am on September 27, 2026 to an "
    "average of 181.9 cent(s)/litre at local stations."
)

CITYNEWS_KITCHENER_HTML = (
    '<div class="float-start">No Change</div> '
    '<a href="http://www.en-pro.com/">En-Pro</a> tells CityNews that prices '
    "are expected to remain unchanged at 12:01am on September 28, 2026 "
    "holding at an average of 181.9 cent(s)/litre at local stations."
)

def test_gaswizard_toronto_end_to_end():
    session = FakeSession({"https://www.gaswizard.ca/toronto": GASWIZARD_TORONTO_HTML})
    data = AffordableEnergyCaProvider("toronto", session=session).fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(1.0)  # 188.9 - 187.9
    assert data["tomorrow_price"] == pytest.approx(188.9)
    assert data["current_price"] == pytest.approx(187.9)
    assert data["trend"] == "rising"
    assert data["provider_name"] == "Affordable Energy (Gas Wizard)"


def test_citynews_toronto_end_to_end():
    session = FakeSession({"https://toronto.citynews.ca/gas-prices/": CITYNEWS_TORONTO_HTML})
    data = CityNewsCaProvider("toronto", session=session).fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(-7.0)
    assert data["tomorrow_price"] == pytest.approx(181.9)
    assert data["current_price"] == pytest.approx(188.9)
    assert data["trend"] == "falling"


def test_citynews_kitchener_no_change_end_to_end():
    session = FakeSession({"https://kitchener.citynews.ca/gas-prices/": CITYNEWS_KITCHENER_HTML})
    data = CityNewsCaProvider("kitchener", session=session).fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(0.0)
    assert data["tomorrow_price"] == pytest.approx(181.9)
    assert data["trend"] == "stable"


def test_gaswizard_no_change_day_still_parses():
    session = FakeSession({"https://www.gaswizard.ca/toronto": GASWIZARD_NO_CHANGE_HTML})
    data = AffordableEnergyCaProvider("toronto", session=session).fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(0.0)
    assert data["tomorrow_price"] == pytest.approx(181.9)
    assert data["current_price"] == pytest.approx(181.9)
    assert data["trend"] == "stable"
    assert "Sep 28, 2026" in data["effective_date_str"]

def test_gaswizard_layout_change_fails_soft():
    session = FakeSession({"https://www.gaswizard.ca/toronto": "<html>redesigned</html>"})
    data = AffordableEnergyCaProvider("toronto", session=session).fetch_data()

    assert data["is_valid"] is False
    assert data["state"] is None


def test_citynews_falls_back_to_second_url_slug():
    session = FakeSession(
        {"https://toronto.citynews.ca/toronto-gas-prices/": CITYNEWS_TORONTO_HTML}
    )
    data = CityNewsCaProvider("toronto", session=session).fetch_data()

    assert data["is_valid"] is True
    assert session.requested == [
        "https://toronto.citynews.ca/gas-prices/",
        "https://toronto.citynews.ca/toronto-gas-prices/",
    ]


def test_citynews_calgary_parked_fails_soft():
    # Calgary's GasBuddy widget isn't resolved yet; it must not crash.
    session = FakeSession({"https://calgary.citynews.ca/gas-prices/": "<html>no price here</html>"})
    data = CityNewsCaProvider("calgary", session=session).fetch_data()

    assert data["is_valid"] is False


GASWIZARD_NO_CHANGE_HTML = """
<ul class="single-city-prices "><h2 class="entry-title">Toronto</h2>
<li><div><span class="daytext">Monday</span> - <span class="datetext">Sep 28, 2026</span></div>
<div class="fueltype"><div class="fueltitle">Regular</div>
<div class="fuelprice"><span class="fuel-price-value">181.9</span> ---</div></div></li>
<li><div><span class="daytext">Sunday</span> - <span class="datetext">Sep 27, 2026</span></div>
<div class="fueltype"><div class="fueltitle">Regular</div>
<div class="fuelprice"><span class="fuel-price-value">181.9</span>
<div class="price-direction pd-down"><span class="price-text">-7&#162;</span></div></div></div></li>
<li><h3>Current Average Price</h3>$1.819</li>
</ul>
"""

def test_gaswizard_no_change_day_still_parses():
    session = FakeSession({"https://www.gaswizard.ca/toronto": GASWIZARD_NO_CHANGE_HTML})
    data = AffordableEnergyCaProvider("toronto", session=session).fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(0.0)
    assert data["tomorrow_price"] == pytest.approx(181.9)
    assert data["current_price"] == pytest.approx(181.9)
    assert data["trend"] == "stable"
    assert "Sep 28, 2026" in data["effective_date_str"]

GASBUDDY_STATION_JSON = {
    "station": {
        "Name": "Costco",
        "Address": "90 Windfields Farm Dr E",
        "City": "Oshawa",
        "State": "ON",
        "ZipCode": "L1H 0A1",
        "Lat": 43.94,
        "Lng": -78.83,
        "APIFuel": [
            {"Id": 1, "Available": True, "DisplayName": "Regular"},
            {"Id": 2, "Available": True, "DisplayName": "Premium"},
        ],
        "Fuels": [
            {"FuelType": 1, "CreditPrice": {"Amount": 1.649, "TimePosted": "/Date(1758931200000)/"}},
            {"FuelType": 2, "CreditPrice": {"Amount": 1.799, "TimePosted": "/Date(1758931200000)/"}},
        ],
    }
}


class FakePostSession(FakeSession):
    """Extends FakeSession with a matching POST, for GasBuddy's endpoint."""

    def __init__(self, json_response):
        super().__init__({})
        self.json_response = json_response
        self.posted_with = None

    def post(self, url, data=None, **kwargs):
        self.posted_with = (url, data)
        resp = FakeResponse("")
        resp.json = lambda: self.json_response
        return resp


def test_gasbuddy_station_end_to_end():
    session = FakePostSession(GASBUDDY_STATION_JSON)
    data = GasBuddyStationProvider("205748", session=session).fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(1.649)
    assert data["current_price"] == pytest.approx(1.649)
    assert data["tomorrow_price"] is None
    assert data["station_name"] == "Costco"
    assert data["city"] == "Oshawa"
    assert session.posted_with == (
        "https://www.gasbuddy.com/gaspricemap/station",
        {"id": "205748", "fuelTypeId": "1"},
    )


def test_gasbuddy_missing_station_fails_soft():
    session = FakePostSession({"station": None})
    data = GasBuddyStationProvider("999999", session=session).fetch_data()
    assert data["is_valid"] is False
