![Smart Fuel Price](custom_components/smart_fuel_price/brand/logo.png)

# Smart Fuel Price Integration for Home Assistant

![Release](https://img.shields.io/github/v/release/meokey/smart-fuel-price)
![HACS Validation](https://github.com/meokey/smart-fuel-price/actions/workflows/release.yml/badge.svg)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)
![License](https://img.shields.io/github/license/meokey/smart-fuel-price)

A Home Assistant custom integration that provides real-time and next-day fuel price predictions for Canadian and global cities across multiple providers.

---

## Features

- **Multi-Provider Architecture**: Supports `AffordableEnergy` (Gas Wizard), `CityNews Canada`, and `GasBuddy` (per-station).
- **UI Configuration (Config Flow)**: A two-step setup — pick a provider, then fill in just the details that provider needs (a city, or GasBuddy station IDs and fuel grades).
- **Multi-Station, Multi-Grade GasBuddy Tracking**: Track several stations at once, each with one or more fuel grades (Regular, Midgrade, Premium, Diesel) — one HA device per station, one sensor per grade.
- **Automatic Area Assignment**: New devices are created with a suggested Area matching their city, so Home Assistant sets this up for you on first install.
- **Dynamic Attribute Filtering (Options Flow)**: Enable or disable specific state attributes via UI settings without modifying code.
- **YAML Migration Support**: Automatically migrates legacy `configuration.yaml` definitions into UI Config Entries seamlessly.

---

## Installation

### Method 1: HACS (Recommended)

1. Open **HACS** in your Home Assistant sidebar.
2. Search for `Smart Fuel Price` under **Integrations**.
3. Click **Download**.
4. Restart Home Assistant Core.

### Method 2: Manual Installation

1. Download the `smart_fuel_price.zip` archive from the latest [Release Page](https://github.com/meokey/smart-fuel-price/releases).
2. Extract the `smart_fuel_price` folder into your Home Assistant directory:
```text
   custom_components/smart_fuel_price/
```
3. Restart Home Assistant Core.

---

## Configuration

After installation, configure your sensors through the Home Assistant UI:

1. Go to **Settings** -> **Devices & Services**.
2. Click **Add Integration** in the bottom right corner.
3. Search for **Smart Fuel Price**.
4. Select your desired **Provider**, then fill in the next step's details
   (a **City**, or GasBuddy **Station ID(s)** and **fuel grade(s)**).
5. Click **Submit**.

> **Note**: You can add multiple instances of this integration for different cities, providers, or station groups!

### Managing Sensor Attributes (Options Flow)

To customize which attributes are sent to your database:

1. Go to **Settings** -> **Devices & Services**.
2. Find your **Smart Fuel Price** integration entry.
3. Click **Configure** (the gear icon).
4. Check the attributes you wish to **disable** and click **Submit**.

### Data caching & refresh threshold

Each entry keeps a local cache of the last fetched data plus its timestamp
(persisted in `.storage`, so it survives restarts). The same Options screen
lets you set a **cache threshold** per entry:

- If the last fetch is *newer* than the threshold, the sensor reuses the
  cached data without hitting the network.
- Presets: **240 min** for forecast providers (Gas Wizard, CityNews),
  **30 min** for GasBuddy. Adjustable from 5 to 1440 minutes.

When a fetch fails but cached data exists, live-price providers (GasBuddy)
keep showing the last known value marked with a `stale: True` attribute
instead of going `unknown` -- useful during rate-limiting episodes.
Forecast providers never serve stale forecasts; they show `unknown` until
fresh data arrives.

Each device also gets a **Refresh data** button entity for a manual,
cache-bypassing fetch at any time.

---

## Supported Providers & Cities

| Provider Identifier | Target Region | Dynamic Cities Supported |
| :--- | :--- | :--- |
| `affordableenergy_ca` | Canada (Nationwide) | `toronto`, `mississauga`, `vancouver`, `calgary`, `ottawa`, `montreal` -- all confirmed live |
| `citynews_ca` | Canada Major Cities | `toronto`, `ottawa`, `kitchener` (`calgary` currently unsupported -- see below) |
| `gasbuddy_ca` | Any station, anywhere GasBuddy has data (GTA included) | N/A -- configured by station ID, not a fixed city list; see [GasBuddy section](#gasbuddy-per-station) below |

> **Note:** Gas Wizard publishes tomorrow's forecast on its own schedule (usually by the evening).
> Until then, its sensors show *unknown* rather than a stale value.

---

## Sensor Naming & Organization

Devices and entities are named **"Smart Fuel Price - `<City>` - `<Provider>`"** (or, for GasBuddy, **"Smart Fuel Price - `<City>` - GasBuddy (`<Station Name>`)"**), so everything this integration creates sorts and groups together in the Home Assistant UI.

Each device is also created with a **suggested Area** matching its city -- Home Assistant will automatically create that Area (if it doesn't already exist) and assign the device to it the first time it's set up. You're free to change this afterward; it's a one-time suggestion, not an enforced setting.

---

## GasBuddy (per-station)

Unlike the other providers, GasBuddy tracks specific gas stations you
choose, not a city average — there's no forecast, just live reported
prices, so its sensors show the **current price** rather than a price
*change*.

**Finding a station ID:**
1. Open https://www.gasbuddy.com/gaspricemap
2. Click a station's price bubble, then click through to its page
3. The station ID is the number at the end of the URL:
   `https://www.gasbuddy.com/station/205748` → ID is `205748`

When configuring, select **GasBuddy (Station)** as the provider, enter
one or more station IDs (comma-separated, e.g. `205748, 123456`), and
pick one or more fuel grades to track (Regular, Midgrade, Premium,
Diesel). One sensor is created per (station, grade) combination, and all
grades for the same station share a single device.

GasBuddy's crowd-sourced prices can change more often than a forecast
updates once a day, so these sensors refresh every 30 minutes rather
than the 4-hour default used by the forecast providers.

*Station price data is retrieved via an endpoint documented by the
[Red5d/ha-gasbuddy](https://github.com/Red5d/ha-gasbuddy) project —
thanks to Red5d and contributors for that groundwork.*

## Upgrading to v2.3.6+

`state` changed meaning: for the forecast providers (Gas Wizard,
CityNews) it's now the **signed price change** in ¢/L (e.g. `-7.0`,
`0.0`, `+4.0`) rather than the current price in $/L. GasBuddy sensors
were unaffected -- their `state` has always been the current price in $.
Check any automations that read a forecast-provider sensor's state
directly.

## Development

### Running tests

```bash
pip install -r requirements-test.txt
pytest            # offline tests (default)
pytest -m live    # live smoke tests against real provider sites
```

`pytest.ini` excludes live tests by default; known-failing live checks are
marked `xfail` rather than skipped.

## License

Distributed under the MIT License. See `LICENSE` for more information.
