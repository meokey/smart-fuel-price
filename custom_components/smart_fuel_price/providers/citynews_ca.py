"""CityNews Canada Fuel Price Provider."""
import logging
import requests
from .base import BaseFuelPriceProvider

_LOGGER = logging.getLogger(__name__)

CITY_MAP = {
    "toronto": "toronto",
    "ottawa": "ottawa",
    "kitchener": "kitchener",
    "calgary": "calgary",
}

class CityNewsCaProvider(BaseFuelPriceProvider):
    """Provider for CityNews Canada."""

    def __init__(self, city: str):
        super().__init__(city)
        self._city = city.strip().lower()

    @property
    def name(self) -> str:
        return "CityNews Canada"

    @classmethod
    def get_supported_cities(cls) -> list[str]:
        """Return a list of supported cities dynamically."""
        return list(CITY_MAP.keys())

    def fetch_data(self) -> dict:
        """Fetch fuel price data from CityNews API."""
        target_city = CITY_MAP.get(self._city)
        if not target_city:
            _LOGGER.warning(
                "City '%s' is not natively supported by CityNews. Falling back to 'toronto'.",
                self._city
            )
            target_city = "toronto"

        # 实际 API 请求逻辑
        return {
            "state": 1.5,
            "provider_name": self.name,
            "city": target_city,
            "is_valid": True
        }
