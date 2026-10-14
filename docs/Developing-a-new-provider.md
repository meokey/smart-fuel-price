# Developing a new provider

This guide is for contributors who want to add a new data source
(a "provider") to the integration — e.g. another forecast site or a
per-station price feed. Providers are small, self-contained plugins:
subclass the base, parse the source, register three lines of wiring.

> Ground rule: **sources are read-only**. The integration only ever
> *fetches* data (plain GET-style requests). Never submit, post, or
> otherwise write back to a source.

## 1. Subclass `BaseFuelPriceProvider`

Create `custom_components/smart_fuel_price/providers/<name>.py`:

```python
from .base import BaseFuelPriceProvider, trend_fields

class MyProvider(BaseFuelPriceProvider):
    @property
    def name(self) -> str:
        return "My Source"

    def _parse_data(self) -> dict:
        html = self._get("https://example.com/prices/toronto").text
        price = ...  # parse it, in cents per litre
        return {
            "state": price,          # the sensor's main value (see schema)
            "current_price": price,
            "is_valid": True,
            **trend_fields(None),
        }
```

You only implement two things:

- **`name`** — display name of the source.
- **`_parse_data()`** — fetch + parse, return a dict of keys (below).
  Return a falsy value (or `{"is_valid": False}`) when parsing fails.
  Raise `RateLimitedError` on HTTP 429 (or 403 where the site uses it
  for bot-protection) so throttling is tracked separately from breakage.

Useful overrides:

| Override | Default | When to change |
|---|---|---|
| `scan_interval` | 4 hours | Live feeds (e.g. per-station): shorter, e.g. 30 min |
| `sensor_name` | `"Price Change"` | Live-price providers: `"Current Price"` |
| `native_unit_of_measurement` | `"¢/L"` | Only if the source isn't cents/litre |
| `requires_api_key` | `False` | `True` if the source needs a key (config flow will prompt) |
| `get_supported_cities()` | `[]` | Static list of city slugs, e.g. `["toronto", "ottawa"]` |
| `discover_cities()` | `None` | Optional live discovery; keep it cheap, callers cache it |
| `source_url` | `None` | Canonical page URL — shown as a link on the device card |
| `cache_key` | `ClassName:city` | Override when the provider has extra identity (e.g. fuel grade) |
| `allow_stale_on_failure` | `False` | `True` for live prices where old data beats no data (served with `stale: True`); keep `False` for forecasts |

Helpers in `base.py`: `self._get(url)` (shared session, browser-like
headers, 10 s timeout), `first_number(text)`, `trend_fields(change)`,
`DEFAULT_HEADERS`.

## 2. The data schema

`_parse_data()` returns keys that update the base result. Core keys:

| Key | Meaning |
|---|---|
| `state` | **The sensor's main value.** Forecast providers: signed price *change* in ¢/L (tomorrow − today). Live providers: current price in ¢/L |
| `current_price` | Today's / current price, ¢/L |
| `tomorrow_price` | Forecast price, ¢/L (`None` for live providers) |
| `effective_date_str` | Human date the forecast applies to, e.g. `"Wednesday Oct 7, 2026"` (`"N/A"` for live) |
| `is_valid` | `True` when parsing succeeded — **required** |
| `trend` / `is_rising` / `is_dropping` | Use `trend_fields(change)` to build these |
| `city` | City slug (base fills this in) |

Any **extra keys you return become sensor attributes** automatically
(e.g. GasBuddy returns `station_name`, `phone`, `address`, `latitude`,
`longitude`, `last_reported_str`). If an attribute should be
user-disableable in the Options flow, also add its key to
`OPTIONAL_ATTRIBUTES` in `const.py`.

Units: keep everything in **cents per litre** and the `¢/L` label —
that's the Canadian pump convention (see [Providers](https://github.com/meokey/smart-fuel-price/wiki/Providers)).

## 3. Wire it up (three places)

1. **`const.py`** — add `"my_key": "Display Name"` to `AVAILABLE_PROVIDERS`
   (the key is what the config entry stores), a preset in
   `DEFAULT_CACHE_TTL_MINUTES`, and any new attribute keys in
   `OPTIONAL_ATTRIBUTES`.
2. **`config_flow.py`** — import your class and add it to
   `_PROVIDER_CLASSES`. If your provider needs extra setup fields
   (station IDs, grades…), extend the `details` step like the GasBuddy
   branch does.
3. **`sensor.py`** — in `async_setup_entry`, add a branch that
   instantiates your provider and defines its sensor specs as
   `(entity_name, value_key, unique_id_suffix)` triples, e.g.
   `[(None, "state", None)]` for a single sensor reading `state`,
   or Gas Wizard's three-sensor layout.

The Last-updated / Update-status sensors and the Manual-refresh button
are created automatically for every device — no extra work needed.

## 4. Tests

- Add offline tests under `tests/` (mock the HTTP layer; never hit the
  real site in offline tests). Run `pytest` — it must stay green.
- Optional live smoke test: mark with the `live` marker (`pytest -m live`
  runs them; they're excluded by default and known-flaky ones are
  `xfail`).

## Checklist before opening a PR

- [ ] Provider subclass with `name` + `_parse_data()`; `is_valid` handled
- [ ] `RateLimitedError` raised on 429/403-style throttling
- [ ] Registered in `const.py`, `config_flow.py`, `sensor.py`
- [ ] Units in ¢/L; read-only access only (no POST/submit)
- [ ] `pytest` green, including new offline tests
- [ ] If you plan to implement it yourself, say so on the tracking issue
      (the issue templates ask) so work doesn't collide
