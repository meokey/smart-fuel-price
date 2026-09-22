"""Fuelwise App Provider."""
import logging
import requests
# from bs4 import BeautifulSoup  # 如果使用了bs4请取消注释
from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

class FuelwiseAppProvider(BaseFuelPriceProvider):
    """Provider for Fuelwise."""

    @property
    def name(self) -> str:
        return "Fuelwise"

    @classmethod
    def get_supported_cities(cls) -> list[str]:
        return ["toronto", "mississauga", "ottawa", "hamilton", "kitchener"]

    def _parse_data(self) -> dict:
        api_url = f"https://api.fuelwise.ca/v1/prices/{self.city}"
        
        response = requests.get(api_url, timeout=self._timeout)
        if response.status_code != 200:
            _LOGGER.warning("[%s] Received non-200 status: %s", self.name, response.status_code)
            return {}

        # 示例：如果是 JSON 返回
        data = response.json()
        parsed = {}
        
        # 边界提取：利用 dict.get 提供安全的 None 返回
        current_price = data.get("current_price")
        if current_price:
            parsed["state"] = float(current_price)
            parsed["is_valid"] = True
            
        return parsed
