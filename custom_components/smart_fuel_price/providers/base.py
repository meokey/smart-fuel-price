"""
Base provider interface for Smart Fuel Price.
All data source plugins must inherit from this class.
"""

import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from abc import ABC, abstractmethod
from typing import Any
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

_LOGGER = logging.getLogger(__name__)

# Politeness delay between city-list probe requests (seconds). Probes run
# rarely (1-week cache) and only for not-yet-verified cities, but when
# they do, don't hammer the source. This is a floor -- the effective gap
# is max(_PROBE_DELAY_SECONDS, min_request_interval()), so a robots.txt
# Crawl-delay above 1s is honored (see filter_cities_with_prices).
_PROBE_DELAY_SECONDS = 1.0

# How long after a failed fetch (with nothing cached) an automatic
# retry is suppressed. A failure seconds ago will almost certainly fail
# the same way -- retrying per sensor/entity just hammers a struggling
# source. Forced (manual) refreshes bypass this; the next scheduled
# poll (15 min default) is far outside the window.
_RETRY_COOLDOWN_SECONDS = 60

# Automatic retry backoff after a failed fetch (#55): 15 -> 30 -> 60 ->
# 60 minutes. Retries are scheduled per provider (not per sensor) via
# async_call_later in sensor.py; each retry is a forced fetch.
_RETRY_BACKOFF_MINUTES = (15, 30, 60, 60)

# Absolute ceiling on automatic retries: per provider+city per UTC day.
# Retries never hammer -- even a permanently dead source costs at most
# 5 extra requests a day.
_MAX_RETRIES_PER_DAY = 5

# robots.txt cache TTL. The file barely changes; refetch at most daily.
_ROBOTS_CACHE_TTL = timedelta(hours=24)

# Floor for min_request_interval() when robots.txt has no Crawl-delay
# (or can't be fetched -- fail-open).
_DEFAULT_MIN_INTERVAL_SECONDS = 1.0


class RateLimitedError(Exception):
    """Raised by providers when the source throttles us (HTTP 429, or 403
    where the site uses it for bot-protection).

    Caught in :meth:`BaseFuelPriceProvider.fetch_data`, which marks the
    result with ``rate_limited: True`` instead of treating it as a generic
    failure -- so status tracking (and the "Update status" sensor) can tell
    "slow down" apart from "broken".
    """


def summarize_fetch_status(statuses: list[str | None]) -> str | None:
    """Worst-of aggregation of per-provider fetch statuses for one device.

    Priority: ``rate_limited`` > ``error`` > ``ok`` -- rate-limiting is
    surfaced first because it has a concrete user action (raise the cache
    threshold). Returns None when no provider has attempted a fetch yet.
    """
    if any(s == "rate_limited" for s in statuses):
        return "rate_limited"
    if any(s == "error" for s in statuses):
        return "error"
    if statuses and all(s == "ok" for s in statuses):
        return "ok"
    return None


def fresh_cache_slot(provider: "BaseFuelPriceProvider", data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build the persisted-cache slot for a fresh, healthy fetch.

    Returns ``{"data": ..., "fetched_at": ...}`` when *data* came from a
    real network fetch (not the TTL cache) and the fetch was a healthy
    serving, else None. "Healthy" means ``is_valid`` *or* the provider's
    last fetch status is ``"ok"``: a GasWizard morning fetch with
    ``tomorrow_pending`` carries fresh data (today's price) even though
    ``is_valid`` is False, and must be persisted too -- otherwise the
    on-disk slot (and "Last updated" after a restart) goes stale every
    day until the evening publish (#78).
    Shared by the setup-time preview persist and the sensor update path so
    the "what counts as a persistable fetch" rule lives in one place --
    and so the "Last updated" timestamp survives restarts faithfully.
    """
    if not data or data.get("from_cache"):
        return None
    if data.get("is_valid") or provider.last_fetch_status == "ok":
        return {
            "data": data,
            "fetched_at": datetime.now(timezone.utc).timestamp(),
        }
    return None


def merge_fetch_cache_slots(
    current: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Merge one entry's freshly-persisted slots into what's on disk.

    Every config entry holds its own in-memory snapshot of the fetch
    cache and saves on its own poll schedule. A plain full-overwrite
    save has a stale-snapshot last-writer-wins race: an entry whose
    snapshot predates another entry's save silently wipes that entry's
    slots from the file (seen live: a warm GasBuddy slot vanished across
    restarts, leaving the price sensor at Unknown with nothing to fall
    back on). Merging fixes it: slot keys are per-provider
    (``provider.cache_key``) and only the owning entry ever writes its
    own keys, so an update can add/refresh but never delete another
    entry's slots. Callers must still serialize load-merge-save.
    """
    current.update(incoming)
    return current

# Several target sites (and third-party widgets embedded on them) block or
# mis-serve requests carrying the default python-requests User-Agent string.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
}

# Matches the first int/decimal number in a string, e.g. "7 cent(s)" -> "7"
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")

def first_number(text: str | None) -> float | None:
    """Extract the first int/decimal number found in text, or None."""
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    return float(match.group(1)) if match else None


def cents_to_dollars(cents: float | None) -> float | None:
    """Convert a cents/litre value to dollars/litre, rounded to 3 places."""
    if cents is None:
        return None
    return round(cents / 100, 3)

def trend_fields(change_cents: float | None) -> dict[str, Any]:
    """Map a signed price change (¢/L) to trend / is_rising / is_dropping."""
    if change_cents is None:
        return {"trend": "unknown", "is_rising": False, "is_dropping": False}
    if change_cents > 0:
        return {"trend": "rising", "is_rising": True, "is_dropping": False}
    if change_cents < 0:
        return {"trend": "falling", "is_rising": False, "is_dropping": True}
    return {"trend": "stable", "is_rising": False, "is_dropping": False}

class BaseFuelPriceProvider(ABC):
    """Abstract Base Class for Fuel Price Providers with built-in Defensiveness."""

    # When True, a failed fetch falls back to the last cached payload
    # (marked stale=True) instead of returning invalid/unknown. Only for
    # providers where slightly old data beats no data -- e.g. live prices
    # behind rate limits. Forecast providers keep this False: a stale
    # forecast would be actively misleading.
    allow_stale_on_failure: bool = False

    # When False, this provider only reports a current snapshot and can never
    # produce a tomorrow_price forecast (e.g. GasBuddy live prices, Halifax
    # static tables). The Buy-now binary sensor is not created for such
    # devices -- it would sit at unknown forever.
    supports_forecast: bool = True

    def __init__(
        self,
        city: str,
        api_key: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._city = city.lower().strip()
        self._api_key = api_key
        self._timeout = 10  # Hard 10-second network timeout boundary.
        self._session = session or self._build_session()
        # Local fetch cache: last payload + when it was fetched.
        # cache_ttl may be overridden (e.g. from the HA options flow);
        # None means "fall back to this provider's scan_interval".
        self.cache_ttl: timedelta | None = None
        self._cached_data: dict[str, Any] | None = None
        self._cached_at: datetime | None = None
        self._last_attempt_at: datetime | None = None
        # Outcome of the last fetch attempt: "ok", "rate_limited", "error",
        # or None when no attempt has been made yet. Drives the per-device
        # "Update status" sensor.
        self._last_fetch_status: str | None = None
        # Whether that attempt was a manual (forced) refresh -- a rate limit
        # hit by an automatic poll suggests raising the cache threshold,
        # while one hit by a manual press needs no such hint.
        self._last_fetch_was_forced: bool = False
        # Serializes the check-then-fetch sequence in get_data(): HA may run
        # coordinator updates on executor threads, so without the lock two
        # threads could pass the TTL check together and fetch twice.
        self._cache_lock = threading.Lock()
        # Automatic-retry state (#55). _consec_failures drives the backoff
        # ladder; _retry_state ({"date": "YYYY-MM-DD", "count": n}) enforces
        # the daily cap and is persisted across restarts (see sensor.py).
        # _retry_handle is an opaque async cancel handle owned by the
        # scheduler in sensor.py; _sensors lists the entities reading from
        # this provider so a retry can refresh them all at once.
        self._consec_failures = 0
        self._retry_state: dict[str, Any] = {"date": None, "count": 0}
        self._retry_handle: Any = None
        self._sensors: list[Any] = []

    @classmethod
    def _build_session(cls) -> requests.Session:
        """Return a requests.Session pre-configured with browser-like headers.

        Transport-level retry (seconds-scale) is mounted here so every
        provider gets it: transient 429/5xx responses are retried in place,
        honoring the server's own ``Retry-After`` header. This complements
        -- not replaces -- the application-level retry backoff (#55),
        which handles persistent failures on a minutes scale.
        """
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        retry = Retry(
            total=2,
            status_forcelist=(429, 500, 502, 503, 504),
            respect_retry_after_header=True,
            backoff_factor=1,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    # ------------------------------------------------------------------
    # robots.txt: one global politeness rule for all providers (#55).
    # ------------------------------------------------------------------
    # Where this provider's robots.txt lives; subclasses must set it.
    _ROBOTS_TXT_URL: str | None = None
    # A representative fetch URL, used for the Disallow canary check.
    _ROBOTS_CHECK_URL: str | None = None

    # Class-level cache: {robots_url: (fetched_at, RobotFileParser | None)}.
    # None (fail-open) is cached too -- a dead robots.txt must not cost a
    # network round-trip on every call.
    _robots_cache: dict[str, tuple[datetime, RobotFileParser | None]] = {}
    _robots_lock = threading.Lock()

    @classmethod
    def _get_robots(cls) -> RobotFileParser | None:
        """Fetch + parse robots.txt, cached for 24h. None means fail-open.

        May do network I/O on a cache miss -- callers in async context
        must run it in an executor (see next_retry_delay usage).
        """
        url = cls._ROBOTS_TXT_URL
        if not url:
            return None
        now = datetime.now(timezone.utc)
        with cls._robots_lock:
            cached = cls._robots_cache.get(url)
            if cached and now - cached[0] < _ROBOTS_CACHE_TTL:
                return cached[1]
        rp: RobotFileParser | None = None
        try:
            resp = requests.get(url, timeout=10, headers=DEFAULT_HEADERS)
            resp.raise_for_status()
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            check = cls._ROBOTS_CHECK_URL
            if check and not rp.can_fetch("*", check):
                # Canary, not enforcement: a broad Disallow must not
                # silently kill the integration -- but it must be visible.
                _LOGGER.warning(
                    "[%s] robots.txt disallows %s -- continuing anyway "
                    "(fail-open); tell the maintainer if the source "
                    "complains.",
                    cls.__name__, check,
                )
        except Exception as err:  # noqa: BLE001 -- robots.txt is best-effort
            _LOGGER.debug(
                "[%s] Could not fetch robots.txt (%s); assuming allowed",
                cls.__name__, err,
            )
        with cls._robots_lock:
            cls._robots_cache[url] = (now, rp)
        return rp

    @classmethod
    def min_request_interval(cls) -> float:
        """Global politeness rule: minimum seconds between requests.

        max(robots.txt Crawl-delay, 1s default). Every request path --
        city probes, automatic retries, manual refreshes -- consults this,
        so anti-abuse behavior lives in one place instead of scattered
        constants.
        """
        rp = cls._get_robots()
        if rp is not None:
            delay = rp.crawl_delay("*")
            if delay is not None:
                return max(float(delay), _DEFAULT_MIN_INTERVAL_SECONDS)
        return _DEFAULT_MIN_INTERVAL_SECONDS

    # ------------------------------------------------------------------
    # Automatic retry state machine (#55).
    # ------------------------------------------------------------------
    def next_retry_delay(self) -> timedelta | None:
        """Delay before the next automatic retry; None = don't retry.

        Retries only happen after a failed attempt (``error`` or
        ``rate_limited``), follow the backoff ladder
        :data:`_RETRY_BACKOFF_MINUTES`, never exceed
        :data:`_MAX_RETRIES_PER_DAY` per UTC day, and never go below
        :meth:`min_request_interval` (the robots.txt rule).

        May do network I/O on a robots.txt cache miss -- callers in async
        context must run it in an executor.
        """
        if self._last_fetch_status not in ("error", "rate_limited"):
            return None
        today = datetime.now(timezone.utc).date().isoformat()
        count = (
            self._retry_state["count"]
            if self._retry_state.get("date") == today
            else 0
        )
        if count >= _MAX_RETRIES_PER_DAY:
            return None
        failures = max(self._consec_failures, 1)
        backoff_minutes = _RETRY_BACKOFF_MINUTES[
            min(failures - 1, len(_RETRY_BACKOFF_MINUTES) - 1)
        ]
        seconds = max(backoff_minutes * 60, self.min_request_interval())
        return timedelta(seconds=seconds)

    def record_retry(self) -> dict[str, Any]:
        """Increment today's retry counter. Returns the state for persisting."""
        today = datetime.now(timezone.utc).date().isoformat()
        if self._retry_state.get("date") != today:
            self._retry_state = {"date": today, "count": 0}
        self._retry_state["count"] += 1
        return dict(self._retry_state)

    def hydrate_retry_state(self, state: dict[str, Any] | None) -> None:
        """Restore the daily retry counter from the persisted store."""
        if (
            isinstance(state, dict)
            and isinstance(state.get("count"), int)
            and state["count"] >= 0
        ):
            self._retry_state = {
                "date": state.get("date"),
                "count": state["count"],
            }

    def cancel_retry(self) -> None:
        """Cancel a scheduled automatic retry, if any (idempotent)."""
        handle, self._retry_handle = self._retry_handle, None
        if handle is not None:
            try:
                handle()
            except Exception:  # noqa: BLE001 -- best-effort cancel
                pass

    @property
    def city(self) -> str:
        """Return selected city."""
        return self._city

    @property
    def api_key(self) -> str | None:
        """Return the configured API key, if any."""
        return self._api_key

    @property
    @abstractmethod
    def name(self) -> str:
        """Return provider name."""

    @property
    def requires_api_key(self) -> bool:
        """Whether this provider needs a user-supplied API key to function.

        Web-scraping providers should leave this as False (the default).
        Providers wrapping a paid/keyed API should override this to True
        so the config flow knows to prompt for it.
        """
        return False

    @property
    def scan_interval(self) -> timedelta:
        """Suggested minimum time between fetches for this provider.

        Providers backed by a slow-changing source (a once-daily
        forecast) should keep this long to avoid hammering the site;
        providers backed by a live, frequently-updated feed should
        override with something shorter.
        """
        return timedelta(hours=4)

    @property
    def sensor_name(self) -> str:
        """Entity name shown in HA, e.g. 'Price Change', 'Current Price'."""
        return "Price Change"

    @property
    def native_unit_of_measurement(self) -> str:
        """Unit of the sensor's native_value."""
        return "¢/L"

    @classmethod
    def get_supported_cities(cls) -> list[str]:
        """Return the static, known-good list of supported cities/regions."""
        return []

    @classmethod
    def discover_cities(cls) -> dict[str, str] | None:
        """Optionally probe the live source for its current city list.

        Returns a mapping of {city_slug: display_name}, or None if this
        provider doesn't support (or hasn't implemented) live discovery --
        callers should then fall back to get_supported_cities().

        This is intentionally NOT abstract: most providers can rely on a
        maintained static list. Implementations should keep the network
        call cheap and idempotent; callers (e.g. config_flow) are expected
        to cache the result between calls (e.g. via HA's Store helper) --
        this method itself does no caching.
        """
        return None

    @classmethod
    def verified_cities(cls) -> frozenset[str]:
        """Cities already known to have price data.

        ``filter_cities_with_prices`` skips these (no probe) and only
        checks genuinely new discoveries. Default empty: every
        discovered city is probed. Providers with a verified static list
        return it here.
        """
        return frozenset()

    @classmethod
    def city_has_prices(cls, city: str, session: requests.Session | None = None) -> bool:
        """Whether a discovered city actually has price data to offer.

        Called to filter live-discovered city lists before they reach the
        config UI, so cities without a parseable price page never become
        selectable. Default True: providers with a curated static list
        don't need this check. ``session`` is a shared session provided
        by the caller for politeness; implementations may ignore it.
        """
        return True

    def _blank_result(self) -> dict[str, Any]:
        """Fail-safe default payload: no usable data.

        Shared by ``fetch_data`` (before parsing) and the retry-cooldown
        path in ``_get_data_locked``, so both report the same shape.
        """
        return {
            "state": None,  # signed price change in ¢/L (tomorrow - current)
            "tomorrow_price": None,  # forecast average, ¢/L
            "current_price": None,  # today's average, ¢/L
            "trend": "unknown",
            "effective_date_str": "N/A",
            "is_valid": False,
            "is_dropping": False,
            "is_rising": False,
            "provider_name": self.name,
            "city": self.city,
        }

    def fetch_data(self) -> dict[str, Any]:
        """
        Template method: Fetch and parse fuel price data securely.
        Handles networking, timeouts, and exception boundaries.
        """
        # Fail-safe default values
        result: dict[str, Any] = self._blank_result()

        try:
            parsed_data = self._parse_data()
            if parsed_data:
                result.update(parsed_data)
        except RateLimitedError as rl_err:
            _LOGGER.info("[%s] Rate limited by source: %s", self.name, rl_err)
            result["rate_limited"] = True
        except requests.exceptions.RequestException as req_err:
            _LOGGER.error("[%s] Network connection error: %s", self.name, req_err)
        except (KeyError, IndexError, ValueError, TypeError) as parse_err:
            _LOGGER.error("[%s] Data parsing/boundary error: %s", self.name, parse_err)
        except Exception as e:  # noqa: BLE001 - defensive top-level boundary
            _LOGGER.error("[%s] Unexpected error during data extraction: %s", self.name, e)

        return result

    @property
    def cache_key(self) -> str:
        """Stable key identifying this provider's cache slot.

        Used for persisting the fetch cache across restarts. Providers
        with extra identity dimensions (e.g. GasBuddy's fuel grade)
        must override this.
        """
        return f"{type(self).__name__}:{self._city}"

    def _effective_ttl(self) -> timedelta:
        return self.cache_ttl if self.cache_ttl is not None else self.scan_interval

    def get_data(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return fuel data, reusing the local cache when it is fresh.

        - Within TTL of the last attempt (and not forced): return the
          cached payload with ``from_cache: True`` -- no network call.
        - Otherwise fetch; on success the cache (data + timestamp) is
          refreshed.
        - A fetch that succeeds but finds tomorrow's forecast not yet
          published (``tomorrow_pending``) counts as a healthy serving:
          today's price is fresh, so the status is ``ok`` and the
          timestamp updates; only the forecast sensors stay unknown.
        - After a failed attempt with nothing cached, automatic retries
          within 60s are suppressed (the failure would just repeat);
          forced refreshes bypass this.
        - On a failed fetch with a warm cache: serve the stale payload
          (``from_cache: True, stale: True``) when
          ``allow_stale_on_failure`` is set, else the invalid result.
        """
        # Hold the lock across the check-and-fetch so concurrent threads
        # serialize instead of issuing duplicate network requests.
        with self._cache_lock:
            return self._get_data_locked(force_refresh)

    def _get_data_locked(self, force_refresh: bool) -> dict[str, Any]:
        """Cache check + fetch; caller must hold ``self._cache_lock``."""
        now = datetime.now(timezone.utc)
        ttl = self._effective_ttl()
        if (
            not force_refresh
            and self._cached_data is not None
            and self._last_attempt_at is not None
            and now - self._last_attempt_at < ttl
        ):
            # Serving valid cached data counts as a healthy serving: without
            # this the "Update status" sensor would sit at Unknown for the
            # whole TTL window -- which is the normal steady state, since a
            # cache hit by design makes no network attempt that could set
            # the status. (Seen live: "Last updated 5 hours ago" next to
            # "Update status Unknown".)
            # But a cache hit must not whitewash a FAILED source: if the
            # last real attempt failed, keep reporting that failure --
            # otherwise the status sensor reads "OK" for hours while the
            # source is down and "Last updated" goes stale beside it.
            # (Seen live: "Last updated 7 hours ago" next to a bogus OK.)
            if self._last_fetch_status not in ("error", "rate_limited"):
                self._last_fetch_status = "ok"
            self._last_fetch_was_forced = False
            cached = dict(self._cached_data)
            cached["from_cache"] = True
            return cached

        last_attempt_at = self._last_attempt_at
        self._last_attempt_at = now
        self._last_fetch_was_forced = force_refresh
        if (
            not force_refresh
            and self._cached_data is None
            and self._last_fetch_status in ("error", "rate_limited")
            and last_attempt_at is not None
            and (now - last_attempt_at).total_seconds() < _RETRY_COOLDOWN_SECONDS
        ):
            # The last attempt just failed and there is nothing cached:
            # another network call right now would almost certainly fail
            # the same way (seen live: one Manual refresh fanning out
            # into a fetch per sensor, each hitting the same timeout).
            # Report the failure without hammering the source. Forced
            # refreshes bypass this -- the user explicitly asked -- and
            # the next scheduled poll is far outside the window.
            data = self._blank_result()
            data["from_cache"] = False
            return data
        data = self.fetch_data()
        # Internal flags only -- must not leak into entity attributes.
        rate_limited = bool(data.pop("rate_limited", False))
        tomorrow_pending = bool(data.pop("tomorrow_pending", False))
        if data.get("is_valid"):
            self._cached_data = dict(data)
            self._cached_at = now
            self._last_fetch_status = "ok"
            self._consec_failures = 0
            data["from_cache"] = False
            return data

        if tomorrow_pending:
            # The fetch succeeded and today's price is fresh; tomorrow's
            # forecast simply isn't published yet (routine every
            # afternoon before the evening publish). This is not a
            # failure: record a healthy serving so "Last updated" and
            # "Update status" stay truthful, and cache today's price for
            # the TTL window. The forecast sensors still read Unknown
            # from the None tomorrow_price/state.
            self._cached_data = dict(data)
            self._cached_at = now
            self._last_fetch_status = "ok"
            self._consec_failures = 0
            data["from_cache"] = False
            return data

        self._last_fetch_status = "rate_limited" if rate_limited else "error"
        self._consec_failures += 1

        if self.allow_stale_on_failure and self._cached_data is not None:
            # Warning (not info): a failing source is the reason "Last
            # updated" goes stale -- it must be visible in the HA log.
            _LOGGER.warning(
                "[%s] Fetch failed for '%s' (%s); serving last cached data (stale).",
                self.name,
                self._city,
                self._last_fetch_status,
            )
            stale = dict(self._cached_data)
            stale["from_cache"] = True
            stale["stale"] = True
            return stale

        _LOGGER.warning(
            "[%s] Fetch failed for '%s' (%s); no cached data to fall back on.",
            self.name,
            self._city,
            self._last_fetch_status,
        )
        data["from_cache"] = False
        return data

    @property
    def source_url(self) -> str | None:
        """Canonical web page for this device's data (city page / station
        page). Shown as a link on the HA device info card so the numbers can
        be checked against the source. None when the provider has no stable
        per-device URL."""
        return None

    @property
    def last_fetch_status(self) -> str | None:
        """Outcome of the last fetch attempt: "ok", "rate_limited",
        "error", or None when no attempt has been made yet."""
        return self._last_fetch_status

    @property
    def last_fetch_was_forced(self) -> bool:
        """Whether the last fetch attempt was a manual (forced) refresh."""
        return self._last_fetch_was_forced

    @property
    def last_successful_fetch(self) -> datetime | None:
        """When this provider last fetched fresh data successfully.

        Updated on every successful fetch (automatic poll or manual
        refresh) and when the persisted cache is hydrated after a restart.
        Drives the per-device "Last updated" timestamp sensor.
        """
        return self._cached_at

    def hydrate_cache(self, data: dict[str, Any], fetched_at: datetime) -> None:
        """Restore a previously persisted cache (e.g. after HA restart)."""
        with self._cache_lock:
            self._cached_data = dict(data)
            self._cached_at = fetched_at
            self._last_attempt_at = fetched_at
            # Serving restored data is healthy: without this the "Update
            # status" sensor sits at Unknown after every restart until the
            # first poll, even though valid data is being served (seen
            # live: status Unknown next to a correct "Last updated" right
            # after a restart, self-correcting to OK on the next poll).
            # The next real fetch attempt overwrites this with the true
            # outcome, so a down source still surfaces as Failed then.
            self._last_fetch_status = "ok"

    @abstractmethod
    def _parse_data(self) -> dict[str, Any]:
        """
        Internal parsing logic to be implemented by child classes.
        Should return a dictionary of successfully parsed keys to update
        the base result.
        """

    def _get(self, url: str, **kwargs: Any) -> requests.Response:
        """GET a URL using the shared session, headers and timeout."""
        kwargs.setdefault("timeout", self._timeout)
        response = self._session.get(url, **kwargs)
        response.raise_for_status()
        return response
def filter_cities_with_prices(provider_cls, cities: list[str]) -> list[str]:
    """Drop cities that have no parseable price page (via city_has_prices).

    Only cities NOT in the provider's verified set are probed -- the
    verified ones were checked before and barely change, so re-probing
    all of them on every refresh would be 50 requests for nothing (and a
    rate-limit risk, correlated across users after a cache-version bump).
    Probes share one session with a politeness delay between them.

    A probe that raises keeps the city (fail-open): one bad probe must
    not wipe the whole list.
    """
    known_good = provider_cls.verified_cities()
    to_probe = [c for c in cities if c not in known_good]
    if not to_probe:
        return list(cities)
    probed_ok: set[str] = set()
    session = provider_cls._build_session()
    # The global politeness rule (#55): never probe faster than the
    # robots.txt Crawl-delay (or the 1s floor).
    probe_gap = max(_PROBE_DELAY_SECONDS, provider_cls.min_request_interval())
    for i, city in enumerate(to_probe):
        if i:
            time.sleep(probe_gap)
        try:
            has = provider_cls.city_has_prices(city, session=session)
        except Exception:  # noqa: BLE001 -- fail-open, see above
            probed_ok.add(city)
            continue
        if has:
            probed_ok.add(city)
        else:
            _LOGGER.info(
                "[%s] '%s' has no price data; excluded from the city list.",
                provider_cls.__name__,
                city,
            )
    return [c for c in cities if c in known_good or c in probed_ok]
