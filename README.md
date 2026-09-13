# Smart Fuel Price for Home Assistant

![Release](https://img.shields.io/github/v/release/meokey/smart-fuel-price)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)

A modular Home Assistant component to track tomorrow's fuel price trends, helping you decide when to fill up your vehicle.

## Supported Providers & Cities

| Provider Key | Primary Region | Supported Cities Example |
|---|---|---|
| `affordableenergy_ca` | Canada (Gas Wizard) | `mississauga`, `toronto`, `vancouver`, `calgary`, `ottawa`, `montreal` |
| `fuelwise_app` | Ontario / GTA | `toronto`, `mississauga`, `ottawa`, `hamilton` |
| `globalpetrolprices` | Global API | *Requires API Key* |
| `citynews_ca` | Canada (CityNews) | `toronto`, `ottawa`, `kitchener`, `calgary` |

## Configuration Example

Add multiple providers or cities to your `configuration.yaml`:

```yaml
sensor:
  # Provider 1: AffordableEnergy for Mississauga
  - platform: smart_fuel_price
    name: "Mississauga Fuel Price Change"
    provider: "affordableenergy_ca"
    city: "mississauga"

  # Provider 2: Fuelwise.app for Toronto with disabled attributes
  - platform: smart_fuel_price
    name: "Toronto Fuel Price Change"
    provider: "fuelwise_app"
    city: "toronto"
    disabled_attributes:
      - "effective_date_str"
      - "provider_name"
# Provider 2: Use CityNews for Ottawa
  - platform: smart_fuel_price
    name: "Ottawa Fuel Price"
    provider: "citynews_ca"
    city: "ottawa"
