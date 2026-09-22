"""Affordable Energy Canada (Gas Wizard) Provider."""
import logging
import requests
from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

class AffordableEnergyCaProvider(BaseFuelPriceProvider):
    """Provider for Gas Wizard."""

    @property
    def name(self) -> str:
        return "Affordable Energy (Gas Wizard)"

    @classmethod
    def get_supported_cities(cls) -> list[str]:
        return ["mississauga", "toronto", "vancouver", "calgary", "ottawa", "montreal"]

    def _parse_data(self) -> dict:
        """Implementation of specific data parsing for Gas Wizard."""
        # Note: replace with your actual API endpoint and params
        api_url = "https://gaswizard.ca/api/your_endpoint" 
        
        response = requests.get(api_url, timeout=self._timeout)
        if response.status_code != 200:
            _LOGGER.warning("[%s] HTTP Error %s", self.name, response.status_code)
            return {}

        data = response.json()
        results_list = data.get("result", [])
        
        # 安全防御：校验数据列表的有效性
        if not results_list or not isinstance(results_list, list):
            _LOGGER.warning("[%s] API returned empty or invalid results array.", self.name)
            return {}
            
        first_item = results_list[0]
        if not isinstance(first_item, dict):
            _LOGGER.warning("[%s] API result structure changed.", self.name)
            return {}

        parsed = {}
        raw_price = first_item.get("price")
        if raw_price is not None:
            parsed["state"] = float(raw_price)
            parsed["is_valid"] = True
            
        trend_val = first_item.get("trend", "").lower()
        if trend_val in ["up", "down", "flat"]:
            parsed["trend"] = trend_val
            parsed["is_dropping"] = (trend_val == "down")
            parsed["is_rising"] = (trend_val == "up")
            
        return parsed
