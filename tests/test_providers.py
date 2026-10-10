"""Offline end-to-end tests: provider.fetch_data() against canned HTML.

A fake requests-style session is injected through the provider's
`session` constructor argument, so no network access is needed.
"""

import pytest
import requests

from datetime import datetime, timedelta, timezone

from sfp_providers.affordableenergy_ca import AffordableEnergyCaProvider
from sfp_providers.citynews_ca import CityNewsCaProvider
from sfp_providers.gasbuddy_ca import GasBuddyStationProvider

class FakeResponse:
    def __init__(self, text, status_code=200, json_data=None):
        self.text = text
        self.status_code = status_code
        self._json_data = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON here")
        return self._json_data


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


CALGARY_PAGE_HTML = """
<html><body>
<td align="center" id="gasbuddy_12661"></td>
<script src="https://df.gasbuddy.com/feed.gdf?k=KEY123&amp;ia=1&amp;i=12661"></script>
</body></html>
"""

CALGARY_FEED_JS = (
    "document.getElementById('city126610').innerHTML='Calgary';"
    "document.getElementById('price126610').innerHTML='169.1';"
    "document.getElementById('trend_img126610').src="
    "'https://df.gasbuddy.com/images/sm_trend_down.gif';"
)

CALGARY_FEED_URL = (
    "https://df.gasbuddy.com/feed.gdf?k=KEY123&ia=1&i=12661"
    "&url=calgary.citynews.ca%2Fcalgary-gas-prices%2F"
)


def test_citynews_calgary_gasbuddy_widget_end_to_end():
    session = FakeSession(
        {
            "https://calgary.citynews.ca/calgary-gas-prices/": CALGARY_PAGE_HTML,
            CALGARY_FEED_URL: CALGARY_FEED_JS,
        }
    )
    provider = CityNewsCaProvider("calgary", session=session)
    data = provider.fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(169.1)
    assert data["current_price"] == pytest.approx(169.1)
    assert data["trend"] == "falling"
    assert data["city"] == "calgary"
    # the gasbuddy layout reports a current average, not a forecast change
    assert provider.sensor_name == "Current Average Price"
    assert provider.allow_stale_on_failure is True
    # widget page slug wins over the soft-404 "gas-prices/" article
    assert session.requested[0] == "https://calgary.citynews.ca/calgary-gas-prices/"


def test_citynews_calgary_without_widget_fails_soft():
    # A Calgary page with no GasBuddy widget must not crash.
    session = FakeSession(
        {
            "https://calgary.citynews.ca/calgary-gas-prices/": "<html>no price here</html>",
            "https://calgary.citynews.ca/gas-prices/": "<html>no price here</html>",
        }
    )
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


def test_gaswizard_forecast_not_published_yet(caplog):
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
    assert data["tomorrow_price"] is None
    # Today's price is known even without a forecast -- it powers the
    # "Today's Price" entity.
    assert data["current_price"] == pytest.approx(187.9)
    # This is a routine transient state, not an error: it must not log at
    # WARNING or above (HA surfaces those in the error-log UI).
    import logging
    assert not [
        r for r in caplog.records
        if r.name == "sfp_providers.affordableenergy_ca"
        and r.levelno >= logging.WARNING
    ]

GASBUDDY_HOME_HTML = (
    '<html><head><script>window.gbcsrf = "tok123";</script></head></html>'
)

GASBUDDY_GRAPHQL_STATION = {
    "id": "205748",
    "name": "Costco",
    "phone": "905-555-0100",
    "priceUnit": "¢/L",
    "currency": "CAD",
    "latitude": 43.94,
    "longitude": -78.83,
    "address": {
        "line1": "90 Windfields Farm Dr E",
        "line2": None,
        "locality": "Oshawa",
        "region": "ON",
        "postalCode": "L1H 0A1",
        "country": "CA",
    },
    "prices": [
        {"fuelProduct": "regular_gas", "longName": "Regular (85-87 Octane)",
         "credit": {"price": 164.9, "formattedPrice": "164.9",
                    "postedTime": "2026-10-07T18:30:00Z", "nickname": "member"},
         "cash": {"price": 164.9, "formattedPrice": "164.9",
                  "postedTime": "2026-10-07T18:30:00Z", "nickname": "member"}},
        {"fuelProduct": "premium_gas", "longName": "Premium (91-93 Octane)",
         "credit": {"price": 179.9, "formattedPrice": "179.9",
                    "postedTime": "2026-10-07T18:30:00Z", "nickname": "member"},
         "cash": {"price": 179.9, "formattedPrice": "179.9",
                  "postedTime": "2026-10-07T18:30:00Z", "nickname": "member"}},
    ],
}


class FakeGasBuddySession(FakeSession):
    """Fakes GasBuddy's GraphQL flow: GET /home (CSRF token) + POST /graphql."""

    def __init__(self, station=None, post_status=200, post_responses=None):
        super().__init__({})
        self.station = station
        self.post_status = post_status
        # Optional per-call script: list of (status, json) for the POST.
        self.post_responses = list(post_responses or [])
        self.get_count = 0
        self.post_count = 0
        self.posted_with = None  # (url, json, headers)

    def get(self, url, **kwargs):
        self.get_count += 1
        return FakeResponse(GASBUDDY_HOME_HTML)

    def post(self, url, json=None, **kwargs):
        self.post_count += 1
        self.posted_with = (url, json, kwargs.get("headers"))
        if self.post_responses:
            status, body = self.post_responses.pop(0)
            return FakeResponse("", status_code=status, json_data=body)
        return FakeResponse(
            "", status_code=self.post_status,
            json_data={"data": {"station": self.station}},
        )

@pytest.fixture(autouse=True)
def _clear_gasbuddy_station_cache():
    GasBuddyStationProvider._clear_station_cache()
    yield
def test_gasbuddy_shares_one_fetch_across_grades_for_same_station():
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    GasBuddyStationProvider("205748", "regular", session=session).fetch_data()
    GasBuddyStationProvider("205748", "premium", session=session).fetch_data()
    assert session.post_count == 1  # 同一站点，第二次该吃缓存
    assert session.get_count == 1  # CSRF token 也只取一次


def test_gasbuddy_rate_limited_fails_soft():
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION, post_status=429)
    data = GasBuddyStationProvider("205748", session=session).fetch_data()
    assert data["is_valid"] is False


def test_gasbuddy_station_end_to_end():
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    data = GasBuddyStationProvider("205748", session=session).fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(164.9)
    assert data["current_price"] == pytest.approx(164.9)
    assert data["tomorrow_price"] is None
    assert data["station_name"] == "Costco"
    assert data["city"] == "Oshawa"
    assert data["phone"] == "905-555-0100"
    assert data["latitude"] == pytest.approx(43.94)
    assert data["longitude"] == pytest.approx(-78.83)

    url, payload, headers = session.posted_with
    assert url == "https://www.gasbuddy.com/graphql"
    assert payload["operationName"] == "GetStation"
    assert payload["variables"] == {"id": "205748"}
    assert "GetStation" in payload["query"]
    assert headers["gbcsrf"] == "tok123"


def test_gasbuddy_amount_reported_as_cents_per_litre():
    """Price is already in cents/L (e.g. 168.9) -- pass it through raw
    with the \u00a2/L unit; never divide."""
    import copy
    station = copy.deepcopy(GASBUDDY_GRAPHQL_STATION)
    station["prices"][0]["credit"]["price"] = 168.9
    session = FakeGasBuddySession(station)
    provider = GasBuddyStationProvider("205748", session=session)
    data = provider.fetch_data()

    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(168.9)
    assert data["current_price"] == pytest.approx(168.9)
    assert provider.native_unit_of_measurement == "\u00a2/L"


def test_gasbuddy_missing_station_fails_soft():
    session = FakeGasBuddySession(None)
    data = GasBuddyStationProvider("999999", session=session).fetch_data()
    assert data["is_valid"] is False


def test_gasbuddy_graphql_errors_fail_soft():
    session = FakeGasBuddySession(
        GASBUDDY_GRAPHQL_STATION,
        post_responses=[(200, {"errors": [{"message": "boom"}]})],
    )
    data = GasBuddyStationProvider("205748", session=session).fetch_data()
    assert data["is_valid"] is False


def test_gasbuddy_missing_grade_fails_soft():
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)  # regular + premium only
    data = GasBuddyStationProvider("205748", "diesel", session=session).fetch_data()
    assert data["is_valid"] is False


def test_gasbuddy_refreshes_stale_token_on_403_then_succeeds():
    """A 403 on the first POST drops the CSRF token and retries once
    with a fresh one -- the Cloudflare-challenge recovery path."""
    session = FakeGasBuddySession(
        GASBUDDY_GRAPHQL_STATION,
        post_responses=[
            (403, None),
            (200, {"data": {"station": GASBUDDY_GRAPHQL_STATION}}),
        ],
    )
    data = GasBuddyStationProvider("205748", session=session).fetch_data()
    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(164.9)
    assert session.post_count == 2
    assert session.get_count == 2  # token refetched after the 403


def test_gasbuddy_csrf_token_extraction():
    from sfp_providers.gasbuddy_ca import _extract_csrf_token
    assert _extract_csrf_token(GASBUDDY_HOME_HTML) == "tok123"
    assert _extract_csrf_token("<html>no token here</html>") is None
    assert _extract_csrf_token("") is None


def test_gasbuddy_force_refresh_bypasses_shared_station_cache():
    """Manual refresh must hit the network even when the shared
    per-station JSON cache is still warm -- otherwise the refresh button
    is a no-op for up to 20 minutes."""
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    provider = GasBuddyStationProvider("205748", session=session)
    provider.get_data()  # warms both the TTL cache and the shared station cache
    assert session.post_count == 1

    provider.get_data()  # TTL cache hit -- no network
    assert session.post_count == 1

    provider.get_data(force_refresh=True)  # must bypass BOTH cache layers
    assert session.post_count == 2


def test_check_station_grades_all_offered():
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    provider = GasBuddyStationProvider("205748", "regular", session=session)
    valid, missing = provider.check_station_grades(["regular", "premium"])
    assert valid is True
    assert missing == []
    assert session.post_count == 1  # one request covers all grades


def test_check_station_grades_reports_missing_grade():
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)  # regular + premium only
    provider = GasBuddyStationProvider("205748", "regular", session=session)
    valid, missing = provider.check_station_grades(["regular", "diesel"])
    assert valid is True
    assert missing == ["diesel"]


def test_check_station_grades_invalid_station():
    session = FakeGasBuddySession(None)
    provider = GasBuddyStationProvider("999999", "regular", session=session)
    valid, missing = provider.check_station_grades(["regular"])
    assert valid is False


def test_cache_hit_marks_status_ok_not_unknown():
    """Regression: in steady state every poll is served from the TTL cache
    (no network attempt), which used to leave last_fetch_status None -- so
    the per-device "Update status" sensor sat at Unknown indefinitely
    (seen live next to a healthy "Last updated")."""
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    provider = GasBuddyStationProvider("205748", session=session)
    provider.get_data()  # real fetch
    assert session.post_count == 1

    # Simulate "after a restart": status unknown, cache hydrated and fresh.
    provider._last_fetch_status = None
    provider._last_attempt_at = datetime.now(timezone.utc)

    data = provider.get_data()
    assert data["from_cache"] is True
    assert session.post_count == 1  # no network attempt...
    assert provider.last_fetch_status == "ok"  # ...but the serving was healthy
    assert provider.last_fetch_was_forced is False


def test_merge_fetch_cache_slots_keeps_other_entries_slots():
    """Regression: the old full-overwrite save let one config entry's
    stale in-memory snapshot wipe another entry's persisted slots
    (seen live: a warm GasBuddy slot vanished across restarts, leaving
    the price sensor at Unknown with nothing to fall back on)."""
    from sfp_providers.base import merge_fetch_cache_slots
    on_disk = {"gasbuddy:191273:regular": {"data": {"state": 165.9}, "fetched_at": 1.0}}
    incoming = {"affordableenergy_ca:toronto": {"data": {"state": 1.0}, "fetched_at": 2.0}}
    merged = merge_fetch_cache_slots(dict(on_disk), incoming)
    assert merged["gasbuddy:191273:regular"]["data"]["state"] == 165.9
    assert merged["affordableenergy_ca:toronto"]["data"]["state"] == 1.0


def test_merge_fetch_cache_slots_incoming_wins_on_overlap():
    """Only the owning entry ever writes its own provider keys, and its
    in-memory snapshot is always the freshest for those keys."""
    from sfp_providers.base import merge_fetch_cache_slots
    on_disk = {"gasbuddy:191273:regular": {"data": {"state": 160.0}, "fetched_at": 1.0}}
    incoming = {"gasbuddy:191273:regular": {"data": {"state": 165.9}, "fetched_at": 2.0}}
    merged = merge_fetch_cache_slots(dict(on_disk), incoming)
    assert merged["gasbuddy:191273:regular"]["data"]["state"] == 165.9

# 追加到 tests/test_providers.py

def test_all_provider_modules_import_cleanly():
    """Guards against NameError-in-annotations bugs that Python 3.14's
    deferred annotation evaluation (PEP 649) can silently mask -- this
    failed to catch citynews_ca.py using Dict/List/Optional/Tuple
    without importing them, since nothing introspected the annotations."""
    import importlib
    for module_name in (
        "base", "vendor_widgets", "citynews_ca",
        "affordableenergy_ca", "gasbuddy_ca",
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


# ---------------------------------------------------------------------------
# Fetch-cache (provider.get_data) tests -- all offline via injected sessions.
# ---------------------------------------------------------------------------

def _valid_gaswizard_provider(session=None):
    session = session or FakeSession(
        {"https://www.gaswizard.ca/toronto": GASWIZARD_TORONTO_HTML}
    )
    provider = AffordableEnergyCaProvider("toronto", session=session)
    provider.cache_ttl = timedelta(minutes=60)
    return provider, session


def test_get_data_caches_within_ttl():
    provider, session = _valid_gaswizard_provider()
    first = provider.get_data()
    assert first["is_valid"] is True
    assert first["from_cache"] is False

    second = provider.get_data()
    assert second["is_valid"] is True
    assert second["from_cache"] is True
    assert len(session.requested) == 1  # second call hit no network


def test_get_data_refetches_after_ttl():
    provider, session = _valid_gaswizard_provider()
    provider.get_data()
    # Pretend the last attempt was 2h ago.
    provider._last_attempt_at = datetime.now(timezone.utc) - timedelta(hours=2)
    data = provider.get_data()
    assert data["from_cache"] is False
    assert len(session.requested) == 2


def test_get_data_force_refresh_bypasses_cache():
    provider, session = _valid_gaswizard_provider()
    provider.get_data()
    data = provider.get_data(force_refresh=True)
    assert data["from_cache"] is False
    assert len(session.requested) == 2


def test_get_data_failed_fetch_without_cache_returns_invalid():
    class _FailSession(FakeSession):
        def get(self, url, **kwargs):
            self.requested.append(url)
            return FakeResponse("", status_code=500)

    provider = AffordableEnergyCaProvider("toronto", session=_FailSession({}))
    provider.cache_ttl = timedelta(minutes=60)
    data = provider.get_data()
    assert data["is_valid"] is False
    assert "stale" not in data


def test_gaswizard_does_not_serve_stale_forecast():
    # Warm the cache with a valid forecast, then the site stops publishing
    # tomorrow's entry: must stay invalid/unknown, never a stale forecast.
    provider, _ = _valid_gaswizard_provider()
    assert provider.get_data()["is_valid"] is True

    today_only = _gaswizard_html(
        (_TODAY, "187.9", " ---"),
        (_TODAY - timedelta(days=1), "187.9", " ---"),
    )
    provider._session = FakeSession({"https://www.gaswizard.ca/toronto": today_only})
    provider._last_attempt_at = None  # force a real refetch
    data = provider.get_data()
    assert data["is_valid"] is False
    assert "stale" not in data


def test_gasbuddy_serves_stale_price_on_rate_limit():
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    provider = GasBuddyStationProvider("205748", "regular", session=session)
    provider.cache_ttl = timedelta(minutes=30)
    first = provider.get_data()
    assert first["is_valid"] is True
    assert first["state"] == pytest.approx(164.9)

    class _RateLimitedSession(FakeGasBuddySession):
        def post(self, url, json=None, **kwargs):
            self.post_count += 1
            return FakeResponse("", status_code=429)

    provider._session = _RateLimitedSession(None)
    GasBuddyStationProvider._clear_station_cache()  # force the POST to run
    provider._last_attempt_at = None
    second = provider.get_data()
    assert second["is_valid"] is True
    assert second["stale"] is True
    assert second["from_cache"] is True
    assert second["state"] == pytest.approx(164.9)


@pytest.mark.parametrize("status_code", [403, 429])
def test_fetch_status_rate_limited(status_code):
    """HTTP 429 (and 403 used for bot-protection) is tracked distinctly
    from generic failures, and the internal flag never leaks into the
    payload that becomes entity attributes."""

    class _LimitedSession(FakeGasBuddySession):
        def post(self, url, json=None, **kwargs):
            return FakeResponse("", status_code=status_code)

    GasBuddyStationProvider._clear_station_cache()
    provider = GasBuddyStationProvider("205748", session=_LimitedSession(None))
    provider.cache_ttl = timedelta(minutes=30)
    data = provider.get_data(force_refresh=True)
    assert data["is_valid"] is False
    assert provider.last_fetch_status == "rate_limited"
    assert "rate_limited" not in data


def test_fetch_status_ok_on_success():
    GasBuddyStationProvider._clear_station_cache()
    provider = GasBuddyStationProvider(
        "205748", session=FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    )
    assert provider.last_fetch_status is None  # no attempt yet
    data = provider.get_data(force_refresh=True)
    assert data["is_valid"] is True
    assert provider.last_fetch_status == "ok"


def test_fetch_status_error_on_server_error():
    class _BrokenSession(FakeGasBuddySession):
        def post(self, url, json=None, **kwargs):
            return FakeResponse("", status_code=500)

    GasBuddyStationProvider._clear_station_cache()
    provider = GasBuddyStationProvider("205748", session=_BrokenSession(None))
    provider.cache_ttl = timedelta(minutes=30)
    data = provider.get_data(force_refresh=True)
    assert data["is_valid"] is False
    assert provider.last_fetch_status == "error"


def test_rate_limited_records_whether_forced():
    """The threshold-hint is only shown for *automatic* polls -- a manual
    press that hits the limit needs no such suggestion."""

    class _LimitedSession(FakeGasBuddySession):
        def post(self, url, json=None, **kwargs):
            return FakeResponse("", status_code=429)

    GasBuddyStationProvider._clear_station_cache()
    provider = GasBuddyStationProvider("205748", session=_LimitedSession(None))
    provider.cache_ttl = timedelta(minutes=30)

    provider.get_data(force_refresh=True)
    assert provider.last_fetch_status == "rate_limited"
    assert provider.last_fetch_was_forced is True

    GasBuddyStationProvider._clear_station_cache()
    provider._last_attempt_at = None  # force another real attempt
    provider.get_data()
    assert provider.last_fetch_status == "rate_limited"
    assert provider.last_fetch_was_forced is False


def test_source_url_defaults_to_none():
    """A provider with no stable per-device URL reports None."""
    from sfp_providers.base import BaseFuelPriceProvider

    class _NoUrlProvider(BaseFuelPriceProvider):
        @property
        def name(self):
            return "No URL"

        def _parse_data(self):
            return {"is_valid": True}

    assert _NoUrlProvider("toronto").source_url is None


def test_gasbuddy_source_url_points_at_station_page():
    # Pattern live-verified: /station/<id> renders the station's page.
    assert (
        GasBuddyStationProvider("191273").source_url
        == "https://www.gasbuddy.com/station/191273"
    )


def test_gaswizard_source_url_points_at_city_page():
    assert (
        AffordableEnergyCaProvider("toronto").source_url
        == "https://www.gaswizard.ca/toronto"
    )
    # Unknown city falls back to the toronto slug, like _parse_data does.
    assert (
        AffordableEnergyCaProvider("atlantis").source_url
        == "https://www.gaswizard.ca/toronto"
    )


def test_citynews_source_url_remembers_winning_page():
    provider = CityNewsCaProvider("toronto")
    assert provider.source_url is None  # nothing parsed yet

    session = FakeSession({"https://toronto.citynews.ca/gas-prices/": CITYNEWS_TORONTO_HTML})
    provider = CityNewsCaProvider("toronto", session=session)
    data = provider.fetch_data()
    assert data["is_valid"] is True
    assert provider.source_url == "https://toronto.citynews.ca/gas-prices/"


def test_summarize_fetch_status_priority():
    from sfp_providers.base import summarize_fetch_status

    assert summarize_fetch_status(["ok", "ok"]) == "ok"
    assert summarize_fetch_status(["ok", "rate_limited"]) == "rate_limited"
    assert summarize_fetch_status(["ok", "error"]) == "error"
    assert summarize_fetch_status(["rate_limited", "error"]) == "rate_limited"
    assert summarize_fetch_status([None, None]) is None
    assert summarize_fetch_status([]) is None


def test_gasbuddy_cache_key_includes_grade():
    a = GasBuddyStationProvider("205748", "regular")
    b = GasBuddyStationProvider("205748", "premium")
    assert a.cache_key != b.cache_key


def test_fresh_cache_slot_only_for_real_fetches():
    """The persist rule shared by setup-preview and sensor updates."""
    from sfp_providers.base import fresh_cache_slot

    provider = GasBuddyStationProvider("205748", session=FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION))
    before = datetime.now(timezone.utc).timestamp()
    slot = fresh_cache_slot(provider, {"is_valid": True, "state": 164.9})
    assert slot is not None
    assert slot["data"] == {"is_valid": True, "state": 164.9}
    assert before <= slot["fetched_at"] <= datetime.now(timezone.utc).timestamp()

    # TTL-cache hits, invalid payloads and empty data are never persisted.
    assert fresh_cache_slot(provider, {"is_valid": True, "from_cache": True}) is None
    assert fresh_cache_slot(provider, {"is_valid": False}) is None
    assert fresh_cache_slot(provider, None) is None
    assert fresh_cache_slot(provider, {}) is None


def test_last_successful_fetch_tracks_fetches():
    """Drives the per-device "Last updated" timestamp sensor."""
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    provider = GasBuddyStationProvider("205748", session=session)
    assert provider.last_successful_fetch is None

    before = datetime.now(timezone.utc)
    data = provider.get_data()
    after = datetime.now(timezone.utc)
    assert data["is_valid"] is True
    assert before <= provider.last_successful_fetch <= after

    # A within-TTL cached read must NOT move the stamp.
    stamp = provider.last_successful_fetch
    provider.get_data()
    assert provider.last_successful_fetch == stamp


def test_last_successful_fetch_restored_from_persisted_cache():
    """After a restart, "Last updated" shows the persisted fetch time."""
    provider = GasBuddyStationProvider("205748", session=FakeGasBuddySession(None))
    ts = datetime(2026, 10, 7, 7, 30, tzinfo=timezone.utc)
    provider.hydrate_cache({"is_valid": True}, ts)
    assert provider.last_successful_fetch == ts


def test_hydrate_cache_serves_without_network():
    provider = AffordableEnergyCaProvider("toronto", session=FakeSession({}))
    provider.cache_ttl = timedelta(minutes=60)
    provider.hydrate_cache({"is_valid": True, "state": 1.5}, datetime.now(timezone.utc))
    data = provider.get_data()
    assert data["from_cache"] is True
    assert data["state"] == 1.5


def test_gaswizard_matches_entries_by_date_not_position():
    # Even if the page listed entries out of order, today/tomorrow must be
    # picked by their calendar date.
    html = _gaswizard_html(
        (_TODAY, "187.9", " ---"),
        (_TODAY + timedelta(days=1), "188.9",
         '<div class="price-direction pd-up"><span class="price-text">+1&#162;</span></div>'),
    )
    session = FakeSession({"https://www.gaswizard.ca/toronto": html})
    data = AffordableEnergyCaProvider("toronto", session=session).fetch_data()

    assert data["is_valid"] is True
    assert data["current_price"] == pytest.approx(187.9)
    assert data["tomorrow_price"] == pytest.approx(188.9)
    assert data["state"] == pytest.approx(1.0)


# --- city_has_prices / filter_cities_with_prices ---

def _patched_session(monkeypatch, pages):
    """Patch CityNewsCaProvider._build_session to return a FakeSession."""
    session = FakeSession(pages)
    monkeypatch.setattr(
        CityNewsCaProvider, "_build_session", classmethod(lambda cls: session)
    )
    return session


def test_city_has_prices_forecast_layout(monkeypatch):
    _patched_session(
        monkeypatch, {"https://toronto.citynews.ca/gas-prices/": CITYNEWS_TORONTO_HTML}
    )
    assert CityNewsCaProvider.city_has_prices("toronto") is True


def test_city_has_prices_gasbuddy_layout(monkeypatch):
    _patched_session(
        monkeypatch,
        {"https://calgary.citynews.ca/calgary-gas-prices/": CALGARY_PAGE_HTML},
    )
    assert CityNewsCaProvider.city_has_prices("calgary") is True


def test_city_has_prices_soft404_excluded(monkeypatch):
    # Edmonton: both candidates are soft-404s to old articles, no markers.
    article = "<html><head><title>Edmonton has some of the lowest gas prices</title></head><body>news</body></html>"
    _patched_session(
        monkeypatch,
        {
            "https://edmonton.citynews.ca/gas-prices/": article,
            "https://edmonton.citynews.ca/edmonton-gas-prices/": article,
        },
    )
    assert CityNewsCaProvider.city_has_prices("edmonton") is False


def test_city_has_prices_defaults_true():
    # Providers with curated static lists keep everything.
    assert AffordableEnergyCaProvider.city_has_prices("toronto") is True
    assert GasBuddyStationProvider.city_has_prices("whatever") is True


def test_filter_cities_with_prices_drops_and_fail_opens(monkeypatch):
    from sfp_providers.base import filter_cities_with_prices

    def fake_has_prices(city):
        if city == "boom":
            raise RuntimeError("probe blew up")
        return city != "edmonton"

    monkeypatch.setattr(CityNewsCaProvider, "city_has_prices", classmethod(lambda cls, c: fake_has_prices(c)))
    result = filter_cities_with_prices(
        CityNewsCaProvider, ["toronto", "edmonton", "boom", "calgary"]
    )
    assert result == ["toronto", "boom", "calgary"]


def test_gaswizard_gta_end_to_end():
    # GTA is a first-class city on gaswizard.ca (its own /gta page with
    # the same single-city-prices markup); live-verified Oct 9 2026.
    html = _gaswizard_html(
        (_TODAY + timedelta(days=1), "182.9",
         '<div class="price-direction pd-down"><span class="price-text">-3&#162;</span></div>'),
        (_TODAY, "185.9",
         '<div class="price-direction pd-down"><span class="price-text">-2&#162;</span></div>'),
    )
    session = FakeSession({"https://www.gaswizard.ca/gta": html})
    provider = AffordableEnergyCaProvider("gta", session=session)
    assert provider.source_url == "https://www.gaswizard.ca/gta"

    data = provider.fetch_data()
    assert data["is_valid"] is True
    assert data["state"] == pytest.approx(-3.0)  # 182.9 - 185.9
    assert data["tomorrow_price"] == pytest.approx(182.9)
    assert data["current_price"] == pytest.approx(185.9)
    assert data["trend"] == "falling"


def test_gaswizard_supported_cities_includes_gta():
    cities = AffordableEnergyCaProvider.get_supported_cities()
    assert "gta" in cities
    assert {"toronto", "mississauga", "vancouver", "calgary", "ottawa", "montreal"} <= set(cities)


def test_cache_hit_preserves_failed_status():
    """Regression: a TTL cache hit after a FAILED fetch must not whitewash
    the status back to "ok" -- otherwise the per-device "Update status"
    sensor reads OK for hours while the source is down (seen live: Calgary
    "Last updated 7 hours ago" next to a bogus OK)."""
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    provider = GasBuddyStationProvider("205748", session=session)
    provider.get_data()  # real fetch -> ok
    assert provider.last_fetch_status == "ok"

    # Simulate a failed fetch: fresh attempt, invalid result.
    provider._last_attempt_at = datetime.now(timezone.utc)
    provider._last_fetch_status = "error"

    data = provider.get_data()  # TTL cache hit, no network
    assert data["from_cache"] is True
    assert session.post_count == 1
    assert provider.last_fetch_status == "error"  # still honest


def test_cache_hit_after_rate_limit_keeps_suggestion_signal():
    """Same masking bug, rate-limited variant: the sensor's "raise the
    cache threshold" hint keys off last_fetch_status == "rate_limited",
    so a cache hit must not clear it either."""
    session = FakeGasBuddySession(GASBUDDY_GRAPHQL_STATION)
    provider = GasBuddyStationProvider("205748", session=session)
    provider.get_data()

    provider._last_attempt_at = datetime.now(timezone.utc)
    provider._last_fetch_status = "rate_limited"

    provider.get_data()  # cache hit
    assert provider.last_fetch_status == "rate_limited"
