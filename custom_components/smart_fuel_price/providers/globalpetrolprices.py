"""GlobalPetrolPrices API Provider."""
import logging
import requests
from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

class GlobalPetrolPricesProvider(BaseFuelPriceProvider):
    """Provider for GlobalPetrolPrices."""

    def __init__(self, api_key: str, city: str):
        # 初始化父类
        super().__init__(city)
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "GlobalPetrolPrices API"

    @classmethod
    def get_supported_cities(cls) -> list[str]:
        # 全局 API 无需预置硬编码列表，返回空列表代表全通过
        return []

    def _parse_data(self) -> dict:
        if not self._api_key:
            _LOGGER.error("[%s] No API key provided.", self.name)
            return {}

        api_url = f"https://globalpetrolprices.com/api/gasoline/{self.city}/"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        
        response = requests.get(api_url, headers=headers, timeout=self._timeout)
        
        if response.status_code in [401, 403]:
            _LOGGER.error("[%s] Authentication failed. Check your API Key.", self.name)
            return {}
        elif response.status_code != 200:
            return {}

        data = response.json()
        parsed = {}
        
        price = data.get("price")
        if price is not None:
            parsed["state"] = float(price)
            parsed["is_valid"] = True
            
        return parsed
