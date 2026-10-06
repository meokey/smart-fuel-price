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

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/Toronto")


def _eastern_today():
    return datetime.now(_EASTERN).date()


def _fmt_date(d):
    # "Oct 6, 2026" -- no zero-padding so it matches the site's format
    return d.strftime("%b") + " " + str(d.day) + ", " + str(d.year)


def _gaswizard_html(first, second):
    """Build a minimal gaswizard.ca/toronto-style fixture.

    first/second are (date, price, change_markup) tuples in page order.
    """
    items = []
    for d, price, extra in (first, second):
        items.append(
            '<li><div><span class="daytext">' + d.strftime("%A") + "</span> - "
            '<span class="datetext">' + _fmt_date(d) + "</span></div>"
            '<div class="fueltype"><div class="fueltitle">Regular</div>'
            '<div class="fuelprice"><span class="fuel-price-value">' + price + "</span>"
            + extra + "</div></div></li>"
        )
    return (
        '<ul class="single-city-prices "><h2 class="entry-title">Toronto</h2>'
        + "".join(items)
        + "</ul>"
    )


# Fixture modelled on the live gaswizard.ca/toronto markup. Dates are dynamic:
# the provider only trusts entries[0] when it is dated *tomorrow*.
_TODAY = _eastern_today()
GASWIZARD_TORONTO_HTML = _gaswizard_html(
    (_TODAY + timedelta(days=1), "188.9",
     '<div class="price-direction pd-up"><span class="price-text">+1&#162;</span></div>'),
    (_TODAY, "187.9",
     '<div class="price-direction pd-up"><span class="price-text">+2&#162;</span></div>'),
)


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


GASWIZARD_NO_CHANGE_HTML = _gaswizard_html(
    (_TODAY + timedelta(days=1), "181.9", " ---"),
    (_TODAY, "181.9",
     '<div class="price-direction pd-down"><span class="price-text">-7&#162;</span></div>'),
)



def test_gaswizard_no_change_day_still_parses():
    session = FakeSession({"https://www.gaswizard.ca/toronto": GASWIZARD_NO_CHANGE_HTML})
    data = AffordableEnergyCaProvider("toronto", session=session).fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(0.0)
    assert data["tomorrow_price"] == pytest.approx(181.9)
    assert data["current_price"] == pytest.approx(181.9)
    assert data["trend"] == "stable"
    assert _fmt_date(_TODAY + timedelta(days=1)) in data["effective_date_str"]


def test_gaswizard_forecast_not_published_yet():
    # Regression test: when the site's newest entry is *today* (tomorrow's
    # forecast not published yet), the provider must report invalid instead
    # of silently passing off today-vs-yesterday as the forecast change.
    html = _gaswizard_html(
        (_TODAY, "187.9", " ---"),
        (_TODAY - timedelta(days=1), "187.9",
         '<div class="price-direction pd-up"><span class="price-text">+2&#162;</span></div>'),
    )
    session = FakeSession({"https://www.gaswizard.ca/toronto": html})
    data = AffordableEnergyCaProvider("toronto", session=session).fetch_data()

    assert data["is_valid"] is False
    assert data["state"] is None

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
        self.post_count = 0  # 新增

    def post(self, url, data=None, **kwargs):
        self.post_count += 1  # 新增
        self.posted_with = (url, data)
        resp = FakeResponse("")
        resp.json = lambda: self.json_response
        return resp

@pytest.fixture(autouse=True)
def _clear_gasbuddy_station_cache():
    GasBuddyStationProvider._clear_station_cache()
    yield
def test_gasbuddy_shares_one_fetch_across_grades_for_same_station():
    session = FakePostSession(GASBUDDY_STATION_JSON)
    GasBuddyStationProvider("205748", "regular", session=session).fetch_data()
    GasBuddyStationProvider("205748", "premium", session=session).fetch_data()
    assert session.post_count == 1  # 同一站点，第二次该吃缓存


def test_gasbuddy_rate_limited_fails_soft():
    class _RateLimitedSession(FakePostSession):
        def post(self, url, data=None, **kwargs):
            self.post_count += 1
            return FakeResponse("", status_code=429)

    session = _RateLimitedSession({})
    data = GasBuddyStationProvider("205748", session=session).fetch_data()
    assert data["is_valid"] is False

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

# 追加到 tests/test_providers.py

def test_all_provider_modules_import_cleanly():
    """Guards against NameError-in-annotations bugs that Python 3.14's
    deferred annotation evaluation (PEP 649) can silently mask -- this
    failed to catch citynews_ca.py using Dict/List/Optional/Tuple
    without importing them, since nothing introspected the annotations."""
    import importlib
    for module_name in (
        "base", "vendor_widgets", "citynews_ca",
        "affordableenergy_ca", "gasbuddy_ca", "fuelwise_app",
    ):
        importlib.import_module(f"sfp_providers.{module_name}")

class FakeTextPostSession(FakeSession):
    """POST returns a plain-text (non-JSON) response, simulating a bot-block page."""

    def __init__(self, text="<html>blocked</html>"):
        super().__init__({})
        self.text_response = text

    def post(self, url, data=None, **kwargs):
        resp = FakeResponse(self.text_response)

        def _raise_json_error():
            import json
            raise json.JSONDecodeError("Expecting value", self.text_response, 0)

        resp.json = _raise_json_error
        return resp

def test_gasbuddy_non_json_response_fails_soft():
    session = FakeTextPostSession()
    data = GasBuddyStationProvider("205748", session=session).fetch_data()
    assert data["is_valid"] is False

def test_city_lists_are_well_formed():
    """Cheap, no-network sanity check on each provider's own city list."""
    from sfp_providers.affordableenergy_ca import AffordableEnergyCaProvider
    from sfp_providers.citynews_ca import CityNewsCaProvider

    for provider_cls in (CityNewsCaProvider, AffordableEnergyCaProvider):
        cities = provider_cls.get_supported_cities()
        assert cities, f"{provider_cls.__name__} returned an empty city list"
        assert len(cities) == len(set(cities)), f"{provider_cls.__name__} has duplicate cities"
        assert all(c == c.lower() for c in cities), f"{provider_cls.__name__} has non-lowercase city slugs"
