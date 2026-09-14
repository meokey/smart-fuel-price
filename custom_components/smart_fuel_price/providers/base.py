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

    @abstractmethod
    def get_supported_cities(self) -> List[str]:
        """Return a list of supported cities/regions for this provider."""
        pass

    @abstractmethod
    def fetch_data(self) -> Dict[str, Any]:
        """
        Fetch and parse fuel price data.
        Must return a dict adhering to the standard schema:
        {
            "state": float or None,          # Price change (+2.0, -4.0, 0.0)
            "tomorrow_price": float or None, # Expected tomorrow price
            "trend": str,                    # "up", "down", "flat", "unknown"
            "effective_date_str": str,      # Raw/formatted effective date
            "is_valid": bool,               # Freshness & validity flag
            "is_dropping": bool,            # True if price drops
            "is_rising": bool,              # True if price rises
            "provider_name": str,           # Name of provider
            "city": str                     # Configured city
        }
        """
        pass
