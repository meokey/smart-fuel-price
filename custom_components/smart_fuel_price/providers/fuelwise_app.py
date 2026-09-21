"""
Provider plugin for Fuelwise.app (Aggregates GasWizard & CityNews data).
"""
import logging
import re
import requests
from typing import List, Dict, Any
from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

SUPPORTED_CITIES = ["toronto", "mississauga", "ottawa", "hamilton", "kitchener", "london"]

class FuelwiseAppProvider(BaseFuelPriceProvider):
    def __init__(self, city: str = "toronto"):
        super().__init__("Fuelwise.app", city)
        self.url = f"https://fuelwise.app/city/{self.city}" if self.city != "toronto" else "https://fuelwise.app/"
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    @classmethod
    def get_supported_cities(cls) -> List[str]:
        return SUPPORTED_CITIES

    def fetch_data(self) -> Dict[str, Any]:
        result = {
            "state": None, "tomorrow_price": None, "trend": "unknown",
            "effective_date_str": "unknown", "is_valid": False,
            "is_dropping": False, "is_rising": False,
            "provider_name": self.name, "city": self.city
        }

        try:
            response = requests.get(self.url, headers=self.headers, timeout=15)
            response.raise_for_status()
            text = re.sub(r'<[^>]+>', ' ', response.text)
            text = re.sub(r'\s+', ' ', text)

            # Match Fuelwise specific summary cards
            change_match = re.search(r'(fall|rise|drop|jump|hold|stay)\s*(?:by)?\s*(\d+(?:\.\d+)?)\s*cents?', text, re.IGNORECASE)
            price_match = re.search(r'(\d+(?:\.\d+)?)\s*cents?/litre', text, re.IGNORECASE)

            if change_match and price_match:
                action = change_match.group(1).lower()
                amount = float(change_match.group(2))
                result["tomorrow_price"] = float(price_match.group(1))
                result["is_valid"] = True

                if action in ['fall', 'drop']:
                    result["state"] = -amount
                    result["trend"] = "down"
                    result["is_dropping"] = True
                elif action in ['rise', 'jump']:
                    result["state"] = amount
                    result["trend"] = "up"
                    result["is_rising"] = True
                else:
                    result["state"] = 0.0
                    result["trend"] = "flat"
            else:
                _LOGGER.warning("Fuelwise.app pattern match failed for city: %s", self.city)

        except Exception as e:
            _LOGGER.error("Error fetching Fuelwise.app data for %s: %s", self.city, e)

        return result
