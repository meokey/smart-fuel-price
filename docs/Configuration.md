# Configuration

## Adding an entry

Settings → Devices & Services → Add Integration → **Smart Fuel Price**.
Two steps: pick a **provider**, then fill in what that provider needs
(a city, or GasBuddy station IDs + fuel grades). You can add multiple
entries — e.g. Toronto via Gas Wizard *and* your local Costco via GasBuddy.

## Options (per entry)

On the integration entry, click the gear icon → **Configure**:

- **Attributes to Disable** — checked attributes are not written to the
  Home Assistant database (useful for trimming DB growth).
- **Cache threshold (minutes)** — how long fetched data is reused before
  hitting the network again. Presets: 240 min for forecast providers
  (Gas Wizard, CityNews), 30 min for GasBuddy. Range 5–1440.

## Entities per entry

Every device gets:

| Entity | Purpose |
|---|---|
| Price sensors | The actual numbers — see [Providers](https://github.com/meokey/smart-fuel-price/wiki/Providers) for what each one means |
| **Last updated** | Timestamp of the last *successful* fetch. The true freshness signal. |
| **Update status** | `OK` / `Rate limited` / `Failed` for the last attempt |
| **Manual refresh** (button) | Fetch now, bypassing the cache |

### Gas Wizard device

Three sensors: **Price Change** (tomorrow minus today, ¢/L), **Today's Price**,
**Tomorrow's Forecast**. The forecast's `effective_date_str` attribute names
the exact date it applies to.

### CityNews device

**Price Change** plus Last updated / Update status. Same forecast semantics
as Gas Wizard.

### GasBuddy device

One sensor per (station, fuel grade): **Current Price (Regular)** etc.
Attributes include `station_name`, `phone`, `address`, `latitude`,
`longitude`, `last_reported_str`, and `stale` (true while serving cached
data during an outage).

## Device & entity naming

Devices are named `Smart Fuel Price - <City> - <Provider>` (GasBuddy:
`Smart Fuel Price - <Station Name> - GasBuddy`), so everything groups
together. Each device suggests an Area matching its city on first setup —
a one-time suggestion you can change freely.
