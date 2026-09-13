![Smart Fuel Price](custom_components/smart_fuel_price/brand/logo.png)

# Smart Fuel Price for Home Assistant

![Release](https://img.shields.io/github/v/release/meokey/smart-fuel-price)
![HACS Validation](https://github.com/meokey/smart-fuel-price/actions/workflows/release.yml/badge.svg)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)
![License](https://img.shields.io/github/license/meokey/smart-fuel-price)

A modular, highly extensible Home Assistant component to track tomorrow's fuel price trends. Built on a Single Source of Truth (SSoT) architecture, it ensures your automations never trigger on stale data, helping you decide exactly when to fill up your vehicle.

---

## 🚀 Installation

### Via HACS (Recommended)
1. Open Home Assistant and navigate to **HACS** -> **Integrations**.
2. Click the three dots `⋮` in the top right corner and select **Custom repositories**.
3. Add `https://github.com/meokey/smart-fuel-price` with the category **Integration**.
4. Search for `Smart Fuel Price` in HACS, click **Install**, and restart Home Assistant.

---

## ⚙️ Configuration

Add the integration to your `configuration.yaml`. You can track multiple cities or use different providers simultaneously by defining multiple sensors.

```yaml
sensor:
  # Example 1: AffordableEnergy for Mississauga (Default Provider)
  - platform: smart_fuel_price
    name: "Mississauga Fuel Price Change"
    provider: "affordableenergy_ca"
    city: "mississauga"

  # Example 2: Fuelwise for Toronto with attribute filtering
  - platform: smart_fuel_price
    name: "Toronto Fuel Price Change"
    provider: "fuelwise_app"
    city: "toronto"
    disabled_attributes:
      - "effective_date_str"
      - "provider_name"

  # Example 3: CityNews for Ottawa
  - platform: smart_fuel_price
    name: "Ottawa Fuel Price"
    provider: "citynews_ca"
    city: "ottawa"
```

### Supported Providers & Cities

| Provider Key | Primary Region | Supported Cities Example |
|---|---|---|
| `affordableenergy_ca` | Canada (Gas Wizard) | `mississauga`, `toronto`, `vancouver`, `calgary`, `ottawa`, `montreal` |
| `fuelwise_app` | Ontario / GTA | `toronto`, `mississauga`, `ottawa`, `hamilton` |
| `citynews_ca` | Canada (CityNews) | `toronto`, `ottawa`, `kitchener`, `calgary` |
| `globalpetrolprices` | Global API | *Requires API Key (Coming Soon)* |

### Attribute Filtering
You can prevent specific attributes from being written to the Home Assistant state machine database by listing them in `disabled_attributes`. 
Available attributes: `tomorrow_price`, `trend`, `effective_date_str`, `is_valid`, `is_dropping`, `is_rising`, `provider_name`, `city`.

---

## 🛠 Developer Guide: Writing a New Provider

This integration utilizes a strict **Provider Pattern**. The core Home Assistant state machine (`sensor.py`) is completely decoupled from the web scraping and API fetching logic. We highly welcome Pull Requests for new data sources (e.g., European, Australian, or US fuel APIs)!

### Step 1: Create the Provider Class
Create a new Python file in `custom_components/smart_fuel_price/providers/` (e.g., `my_local_gas.py`). Inherit from `BaseFuelPriceProvider` and implement `get_supported_cities()` and `fetch_data()`.

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

### Step 2: Register the Provider
Open `custom_components/smart_fuel_price/sensor.py`, import your newly created class at the top, and add it to the factory router inside the `setup_platform()` function. Submit your PR!
