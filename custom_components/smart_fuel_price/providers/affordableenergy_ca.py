"""
Provider plugin for AffordableEnergy.ca (Gas Wizard by Dan McTeague).
Supports dynamic city validation across Canada.
"""
import logging
import re
import requests
from typing import List, Dict, Any
from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

SUPPORTED_CITIES = [
    "toronto", "mississauga", "brampton", "vancouver", "calgary", 
    "edmonton", "ottawa", "montreal", "winnipeg", "halifax", "victoria", "hamilton"
]

class AffordableEnergyCaProvider(BaseFuelPriceProvider):
    def __init__(self, city: str = "mississauga"):
        super().__init__("AffordableEnergy.ca", city)
        if self.city not in SUPPORTED_CITIES:
            _LOGGER.warning(
                "City '%s' not in preset list for AffordableEnergy. Attempting fetch anyway.", self.city
            )
        self.url = f"https://www.affordableenergy.ca/gas-prices/{self.city}/"
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    def get_supported_cities(self) -> List[str]:
        return SUPPORTED_CITIES

    def fetch_data(self) -> Dict[str, Any]:
        result = {
            "state": None, "tomorrow_price": None, "trend": "unknown",
            "effective_date_str": "tomorrow", "is_valid": False,
            "is_dropping": False, "is_rising": False,
            "provider_name": self.name, "city": self.city
        }

        try:
            response = requests.get(self.url, headers=self.headers, timeout=15)
            response.raise_for_status()
            text = re.sub(r'<[^>]+>', ' ', response.text)
            text = re.sub(r'\s+', ' ', text)

            # Match format: "forecast at 186.9¢/L, up 8.0¢" or "down 4.0¢"
            match = re.search(
                r'forecast at (\d+(?:\.\d+)?)¢/L,\s*(up|down|unchanged)(?:\s+(\d+(?:\.\d+)?)¢)?', 
                text, re.IGNORECASE
            )

            if match:
                result["tomorrow_price"] = float(match.group(1))
                action = match.group(2).lower()
                amount = float(match.group(3)) if match.group(3) else 0.0
                result["is_valid"] = True

                if action == 'down':
                    result["state"] = -amount
                    result["trend"] = "down"
                    result["is_dropping"] = True
                elif action == 'up':
                    result["state"] = amount
                    result["trend"] = "up"
                    result["is_rising"] = True
                else:
                    result["state"] = 0.0
                    result["trend"] = "flat"
            else:
                _LOGGER.warning("AffordableEnergy pattern match failed for city: %s", self.city)

        except Exception as e:
            _LOGGER.error("Error fetching AffordableEnergy data for %s: %s", self.city, e)

        return result
