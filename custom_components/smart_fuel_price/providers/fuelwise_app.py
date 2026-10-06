"""Fuelwise App Provider (parked: its backing API is not publicly available)."""
import logging

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

        # Uses the shared session with browser-like headers (base._get);
        # non-200 responses raise and are soft-failed by fetch_data().
        data = self._get(api_url).json()
        parsed = {}

        # 边界提取：利用 dict.get 提供安全的 None 返回
        current_price = data.get("current_price")
        if current_price:
            parsed["state"] = float(current_price)
            parsed["is_valid"] = True

        return parsed
