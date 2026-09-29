![Smart Fuel Price](custom_components/smart_fuel_price/brand/logo.png)

# Smart Fuel Price Integration for Home Assistant

![Release](https://img.shields.io/github/v/release/meokey/smart-fuel-price)
![HACS Validation](https://github.com/meokey/smart-fuel-price/actions/workflows/release.yml/badge.svg)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)
![License](https://img.shields.io/github/license/meokey/smart-fuel-price)

A Home Assistant custom integration that provides real-time and next-day fuel price predictions for Canadian and global cities across multiple providers.

---

## Features

- **Multi-Provider Architecture**: Supports `AffordableEnergy` (Gas Wizard), `Fuelwise`, `CityNews Canada`, and `GlobalPetrolPrices`.
- **UI Configuration (Config Flow)**: Easily add and configure multiple fuel sensors directly from Home Assistant Devices & Services.
- **Dynamic Attribute Filtering (Options Flow)**: Enable or disable specific state attributes via UI settings without modifying code.
- **Auto Location Detection**: Guesses the closest supported city based on your Home Assistant zone location.
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
4. Select your desired **Provider** and **City** from the dynamic dropdown menu.
5. Click **Submit**.

> **Note**: You can add multiple instances of this integration for different cities or providers!

### Managing Sensor Attributes (Options Flow)

To customize which attributes are sent to your database:

1. Go to **Settings** -> **Devices & Services**.
2. Find your **Smart Fuel Price** integration entry.
3. Click **Configure** (the gear icon).
4. Check the attributes you wish to **disable** and click **Submit**.

---

## Supported Providers & Cities

| Provider Identifier | Target Region | Dynamic Cities Supported |
| :--- | :--- | :--- |
| `affordableenergy_ca` | Canada (Nationwide) | `mississauga`, `toronto`, `vancouver`, `calgary`, `ottawa`, `montreal` |
| `fuelwise_app` | Ontario / GTA | `toronto`, `mississauga`, `ottawa`, `hamilton`, `kitchener` |
| `citynews_ca` | Canada Major Cities | `toronto`, `ottawa`, `kitchener`, `calgary` |
| `globalpetrolprices` | Global (API Key required) | Custom City Query |

---

## GasBuddy (per-station)

Unlike the other providers, GasBuddy tracks specific gas stations you
choose, not a city average — there's no forecast, just live reported
prices.

**Finding a station ID:**
1. Open https://www.gasbuddy.com/gaspricemap
2. Click a station's price bubble, then click through to its page
3. The station ID is the number at the end of the URL:
   `https://www.gasbuddy.com/station/205748` → ID is `205748`

When configuring, select **GasBuddy (Station)** as the provider and
enter one or more station IDs, comma-separated (e.g. `205748, 123456`).
One sensor is created per station.

*Station price data is retrieved via an endpoint documented by the
[Red5d/ha-gasbuddy](https://github.com/Red5d/ha-gasbuddy) project —
thanks to Red5d and contributors for that groundwork.*

## Upgrading to v2.3.6+

`state` changed meaning: it's now the **signed price change** in ¢/L
(e.g. `-7.0`, `0.0`, `+4.0`) rather than the current price in $/L.
Check any automations that read this sensor's state directly.

## License

Distributed under the MIT License. See `LICENSE` for more information.
