"""
Base provider interface for Smart Fuel Price.
All data source plugins must inherit from this class.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseFuelPriceProvider(ABC):
    """Abstract Base Class for Fuel Price Providers."""

    def __init__(self, name: str, city: str = ""):
        self.name = name
        self.city = city.lower().strip()

    @classmethod
    def get_supported_cities(cls) -> List[str]:
        """Return a list of supported cities/regions for this provider."""
        return []

    @abstractmethod
    def fetch_data(self) -> Dict[str, Any]:
        """
        Fetch and parse fuel price data.
        # ... 原样保留你的注释 ...
        """
        pass
