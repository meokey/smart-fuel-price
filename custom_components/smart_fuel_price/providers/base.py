"""
Base provider interface for Smart Fuel Price.
All data source plugins must inherit from this class.
"""
import logging
import requests
from abc import ABC, abstractmethod
from typing import Dict, Any, List

_LOGGER = logging.getLogger(__name__)

class BaseFuelPriceProvider(ABC):
    """Abstract Base Class for Fuel Price Providers with built-in Defensiveness."""

    def __init__(self, city: str):
        self._city = city.lower().strip()
        self._timeout = 10  # 强制 10 秒网络超时边界

    @property
    def city(self) -> str:
        """Return selected city."""
        return self._city

    @property
    @abstractmethod
    def name(self) -> str:
        """Return provider name."""
        pass

    @classmethod
    def get_supported_cities(cls) -> List[str]:
        """Return a list of supported cities/regions for this provider."""
        return []

    def fetch_data(self) -> Dict[str, Any]:
        """
        Template method: Fetch and parse fuel price data securely.
        Handles networking, timeouts, and exception boundaries.
        """
        # Fail-safe default values
        result = {
            "state": None,
            "tomorrow_price": None,
            "trend": "unknown",
            "effective_date_str": "N/A",
            "is_valid": False,
            "is_dropping": False,
            "is_rising": False,
            "provider_name": self.name,
            "city": self.city
        }

        try:
            # 执行子类特有的请求与解析
            parsed_data = self._parse_data()
            if parsed_data:
                # 合并解析出的有效数据
                result.update(parsed_data)
        except requests.exceptions.RequestException as req_err:
            _LOGGER.error("[%s] Network connection error: %s", self.name, req_err)
        except (KeyError, IndexError, ValueError, TypeError) as parse_err:
            _LOGGER.error("[%s] Data parsing/boundary error: %s", self.name, parse_err)
        except Exception as e:
            _LOGGER.error("[%s] Unexpected error during data extraction: %s", self.name, e)

        return result

    @abstractmethod
    def _parse_data(self) -> Dict[str, Any]:
        """
        Internal parsing logic to be implemented by child classes.
        Should return a dictionary of successfully parsed keys to update the base result.
        """
        pass
