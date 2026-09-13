"""
Provider plugin for CityNews Canada.
Scrapes the expected fuel price changes from CityNews trackers across different cities.
"""
import logging
import re
import requests
from typing import List, Dict, Any
from datetime import datetime, timedelta
import homeassistant.util.dt as dt_util

from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

# Routing map for different city endpoints
CITY_URLS = {
    "toronto": "https://toronto.citynews.ca/toronto-gta-gas-prices/",
    "ottawa": "https://ottawa.citynews.ca/gas-prices/",
    "kitchener": "https://kitchener.citynews.ca/kitchener-regional-gas-prices/",
    "calgary": "https://calgary.citynews.ca/calgary-gas-prices/"
}

class CityNewsCaProvider(BaseFuelPriceProvider):
    def __init__(self, city: str = "toronto"):
        super().__init__("CityNews.ca", city)
        
        # Validate supported city, fallback to toronto if invalid
        if self.city not in CITY_URLS:
            _LOGGER.warning(
                "City '%s' is not supported by CityNews plugin. Falling back to 'toronto'.", 
                self.city
            )
            self.city = "toronto"
            
        self.url = CITY_URLS[self.city]
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    def get_supported_cities(self) -> List[str]:
        return list(CITY_URLS.keys())

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
            
            # Strip HTML tags for clean regex processing
            text_content = re.sub(r'<[^>]+>', ' ', response.text)
            text_content = re.sub(r'\s+', ' ', text_content)
            
            change_match = re.search(r'expected to (fall|rise|drop|jump|hold|remain|stay)(?:\s+by)?(?:\s+(\d+(?:\.\d+)?)\s*cent)?', text_content, re.IGNORECASE)
            price_match = re.search(r'average of (\d+(?:\.\d+)?)\s*cent', text_content, re.IGNORECASE)
            date_match = re.search(r'at \d{1,2}:\d{2}[ap]m on ([A-Za-z]+ \d{1,2}, \d{4})', text_content, re.IGNORECASE)
            
            if change_match and price_match and date_match:
                action = change_match.group(1).lower()
                amount_str = change_match.group(2)
                amount = float(amount_str) if amount_str else 0.0
                result["tomorrow_price"] = float(price_match.group(1))
                
                # SSoT Validation: Explicitly check if effective date matches tomorrow
                effective_date_str = date_match.group(1)
                result["effective_date_str"] = effective_date_str
                
                try:
                    effective_date = datetime.strptime(effective_date_str, "%B %d, %Y").date()
                    tomorrow = dt_util.now().date() + timedelta(days=1)
                    
                    if effective_date == tomorrow:
                        result["is_valid"] = True
                    else:
                        _LOGGER.warning("Data is stale. Effective date %s != tomorrow %s", effective_date, tomorrow)
                except ValueError as e:
                    _LOGGER.error("Failed to parse date from CityNews: %s", e)
                    
                if result["is_valid"]:
                    result["is_dropping"] = action in ['fall', 'drop']
                    result["is_rising"] = action in ['rise', 'jump']
                    
                    if result["is_dropping"]:
                        result["state"] = -amount
                        result["trend"] = "down"
                    elif result["is_rising"]:
                        result["state"] = amount
                        result["trend"] = "up"
                    else:
                        result["state"] = 0.0
                        result["trend"] = "flat"
            else:
                _LOGGER.warning("Regex pattern did not match for city: %s", self.city)

        except Exception as e:
            _LOGGER.error("Error fetching data from CityNews for %s: %s", self.city, e)

        return result
