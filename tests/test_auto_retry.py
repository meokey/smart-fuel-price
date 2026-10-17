"""Offline tests for #55: automatic retry with anti-abuse design.

Covers the retry state machine in providers/base.py (backoff ladder,
daily cap, persistence helpers), the robots.txt global politeness rule,
and the transport-level urllib3 retry mounted on every session.

homeassistant isn't needed for any of this -- providers only need
``requests`` (and urllib3, which ships with it).
"""

from datetime import datetime, timedelta, timezone
from urllib.robotparser import RobotFileParser

import pytest
import requests

from sfp_providers.affordableenergy_ca import AffordableEnergyCaProvider
from sfp_providers.base import (
    _MAX_RETRIES_PER_DAY,
    _RETRY_BACKOFF_MINUTES,
    BaseFuelPriceProvider,
)


class RetryTestProvider(AffordableEnergyCaProvider):
    """No robots.txt URL -> min_request_interval() never touches network."""

    _ROBOTS_TXT_URL = None
    _ROBOTS_CHECK_URL = None


@pytest.fixture
def provider():
    return RetryTestProvider("toronto")


@pytest.fixture
def clean_robots_cache():
    BaseFuelPriceProvider._robots_cache.clear()
    yield
    BaseFuelPriceProvider._robots_cache.clear()


def _fail(provider, n=1):
    provider._last_fetch_status = "error"
    provider._consec_failures = n


# ------------------------------------------------------------------
# Backoff ladder
# ------------------------------------------------------------------

def test_no_retry_when_healthy(provider):
    provider._last_fetch_status = "ok"
    provider._consec_failures = 0
    assert provider.next_retry_delay() is None


def test_no_retry_before_first_attempt(provider):
    assert provider._last_fetch_status is None
    assert provider.next_retry_delay() is None


def test_backoff_ladder(provider):
    expected_minutes = [15, 30, 60, 60, 60]
    for failures, minutes in enumerate(expected_minutes, start=1):
        _fail(provider, n=failures)
        delay = provider.next_retry_delay()
        assert delay == timedelta(minutes=minutes), f"failures={failures}"


def test_backoff_ladder_documented_shape():
    assert _RETRY_BACKOFF_MINUTES == (15, 30, 60, 60)


def test_retry_on_rate_limited_too(provider):
    provider._last_fetch_status = "rate_limited"
    provider._consec_failures = 2
    assert provider.next_retry_delay() == timedelta(minutes=30)


# ------------------------------------------------------------------
# Daily cap
# ------------------------------------------------------------------

def test_daily_cap_blocks_scheduling(provider):
    _fail(provider, n=1)
    for _ in range(_MAX_RETRIES_PER_DAY):
        state = provider.record_retry()
    assert state["count"] == _MAX_RETRIES_PER_DAY
    assert provider.next_retry_delay() is None


def test_cap_resets_next_day(provider):
    _fail(provider, n=1)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    provider._retry_state = {"date": yesterday, "count": _MAX_RETRIES_PER_DAY}
    # A new day: the stale counter must not block today's retries.
    assert provider.next_retry_delay() == timedelta(minutes=15)
    state = provider.record_retry()
    assert state["count"] == 1
    assert state["date"] == datetime.now(timezone.utc).date().isoformat()


def test_record_and_hydrate_roundtrip(provider):
    _fail(provider, n=1)
    provider.record_retry()
    provider.record_retry()
    saved = dict(provider._retry_state)

    fresh = RetryTestProvider("toronto")
    fresh.hydrate_retry_state(saved)
    assert fresh._retry_state == saved
    # ...and the restored counter still enforces the cap.
    for _ in range(_MAX_RETRIES_PER_DAY - 2):
        fresh.record_retry()
    _fail(fresh, n=1)
    assert fresh.next_retry_delay() is None


@pytest.mark.parametrize("bad", [None, {}, {"count": "x"}, {"count": -1}, []])
def test_hydrate_rejects_garbage(provider, bad):
    provider.hydrate_retry_state(bad)
    assert provider._retry_state == {"date": None, "count": 0}


def test_cancel_retry_idempotent(provider):
    provider.cancel_retry()  # no handle -- must not raise
    called = []
    provider._retry_handle = lambda: called.append("cancelled")
    provider.cancel_retry()
    assert called == ["cancelled"]
    assert provider._retry_handle is None
    provider.cancel_retry()  # second cancel -- still fine


# ------------------------------------------------------------------
# robots.txt global politeness rule
# ------------------------------------------------------------------

def _parse_robots(text: str) -> RobotFileParser:
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    return rp


def test_min_interval_defaults_without_robots_url(provider):
    assert provider.min_request_interval() == 1.0


def test_crawl_delay_honored(clean_robots_cache):
    class P(AffordableEnergyCaProvider):
        _ROBOTS_TXT_URL = "https://example.test/robots.txt"

    P._robots_cache["https://example.test/robots.txt"] = (
        datetime.now(timezone.utc),
        _parse_robots("User-agent: *\nCrawl-delay: 10\n"),
    )
    assert P.min_request_interval() == 10.0


def test_crawl_delay_below_floor_uses_floor(clean_robots_cache):
    class P(AffordableEnergyCaProvider):
        _ROBOTS_TXT_URL = "https://example.test/robots.txt"

    P._robots_cache["https://example.test/robots.txt"] = (
        datetime.now(timezone.utc),
        _parse_robots("User-agent: *\nCrawl-delay: 0.2\n"),
    )
    assert P.min_request_interval() == 1.0


def test_robots_fetch_failure_is_fail_open(clean_robots_cache, monkeypatch):
    class P(AffordableEnergyCaProvider):
        _ROBOTS_TXT_URL = "https://example.test/robots.txt"

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("nope")

    monkeypatch.setattr(requests, "get", boom)
    assert P.min_request_interval() == 1.0  # fail-open, no raise
    # ...and the failure itself is cached (no retry storm).
    assert P._robots_cache["https://example.test/robots.txt"][1] is None


def test_disallow_warns_but_does_not_block(clean_robots_cache, monkeypatch, caplog):
    class P(AffordableEnergyCaProvider):
        _ROBOTS_TXT_URL = "https://example.test/robots.txt"
        _ROBOTS_CHECK_URL = "https://example.test/gas-prices/"

    class Resp:
        text = "User-agent: *\nDisallow: /gas-prices/\n"
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())
    with caplog.at_level("WARNING"):
        rp = P._get_robots()
    assert rp is not None
    assert not rp.can_fetch("*", "https://example.test/gas-prices/")
    assert "robots.txt disallows" in caplog.text


def test_robots_cached_for_24h(clean_robots_cache, monkeypatch):
    class P(AffordableEnergyCaProvider):
        _ROBOTS_TXT_URL = "https://example.test/robots.txt"

    calls = []

    class Resp:
        text = "User-agent: *\nCrawl-delay: 5\n"
        status_code = 200

        def raise_for_status(self):
            pass

    def fake_get(*a, **k):
        calls.append(a)
        return Resp()

    monkeypatch.setattr(requests, "get", fake_get)
    assert P.min_request_interval() == 5.0
    assert P.min_request_interval() == 5.0
    assert len(calls) == 1


def test_retry_delay_never_below_crawl_delay(clean_robots_cache):
    class P(AffordableEnergyCaProvider):
        _ROBOTS_TXT_URL = "https://example.test/robots.txt"

    P._robots_cache["https://example.test/robots.txt"] = (
        datetime.now(timezone.utc),
        _parse_robots("User-agent: *\nCrawl-delay: 1200\n"),  # 20 min
    )
    p = P("toronto")
    _fail(p, n=1)  # backoff says 15 min, robots says 20 min
    assert p.next_retry_delay() == timedelta(minutes=20)


# ------------------------------------------------------------------
# Transport-level retry (urllib3)
# ------------------------------------------------------------------

def test_session_mounts_retry_adapter(provider):
    adapter = provider._session.get_adapter("https://example.test/")
    retry = adapter.max_retries
    assert 429 in retry.status_forcelist
    assert 403 not in retry.status_forcelist  # 403 is not transient
    assert retry.respect_retry_after_header is True
    assert retry.total == 2
