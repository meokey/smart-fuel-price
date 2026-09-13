# Smart Fuel Price for Home Assistant

![Release](https://img.shields.io/github/v/release/meokey/smart-fuel-price)
![HACS Validation](https://github.com/meokey/smart-fuel-price/actions/workflows/release.yml/badge.svg)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)

A modular Home Assistant component to track tomorrow's fuel price trends, helping you decide when to fill up your vehicle.

## Supported Providers & Cities

| Provider Key | Primary Region | Supported Cities Example |
|---|---|---|
| `affordableenergy_ca` | Canada (Gas Wizard) | `mississauga`, `toronto`, `vancouver`, `calgary`, `ottawa`, `montreal` |
| `fuelwise_app` | Ontario / GTA | `toronto`, `mississauga`, `ottawa`, `hamilton` |
| `globalpetrolprices` | Global API | *Requires API Key* |
| `citynews_ca` | Canada (CityNews) | `toronto`, `ottawa`, `kitchener`, `calgary` |

## Attribute Filtering
You can prevent specific attributes from being written to the Home Assistant state machine by listing them in disabled_attributes.
Available attributes: tomorrow_price, trend, effective_date_str, is_valid, is_dropping, is_rising, provider_name, city.

🛠 Developer Guide: Writing a New Provider
This integration uses a Provider Pattern. The core HA integration (sensor.py) is decoupled from the web scraping/API logic. We welcome Pull Requests for new data sources!

1. Create the Provider Class
Create a new Python file in custom_components/smart_fuel_price/providers/ (e.g., my_local_gas.py). Inherit from BaseFuelPriceProvider and implement get_supported_cities() and fetch_data().

```python
from typing import List, Dict, Any
from .base import BaseFuelPriceProvider

class MyLocalGasProvider(BaseFuelPriceProvider):
    def __init__(self, city: str = ""):
        super().__init__("MyLocalGas", city)
        self.url = f"[https://api.mylocalgas.com/prices/](https://api.mylocalgas.com/prices/){self.city}"

    def get_supported_cities(self) -> List[str]:
        return ["london", "manchester"]

    def fetch_data(self) -> Dict[str, Any]:
        # Implement your scraping or API fetching logic here
        return {
            "state": -2.0,                  # Price drop amount (float)
            "tomorrow_price": 150.0,        # Expected final price
            "trend": "down",                # 'up', 'down', or 'flat'
            "effective_date_str": "...",    # Raw date string
            "is_valid": True,               # Freshness validation
            "is_dropping": True,
            "is_rising": False,
            "provider_name": self.name,
            "city": self.city
        }
```

2. Register the Provider
Open custom_components/smart_fuel_price/sensor.py, import your new class, and add it to the factory router inside setup_platform().

3. Configuration Example

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
# Provider 3: Use CityNews for Ottawa
  - platform: smart_fuel_price
    name: "Ottawa Fuel Price"
    provider: "citynews_ca"
    city: "ottawa"
```
