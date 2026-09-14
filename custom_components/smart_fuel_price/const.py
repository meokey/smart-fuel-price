"""Constants for the Smart Fuel Price integration."""

DOMAIN = "smart_fuel_price"
DEFAULT_NAME = "Tomorrow Fuel Price Change"

CONF_PROVIDER = "provider"
CONF_CITY = "city"
CONF_API_KEY = "api_key"
CONF_DISABLED_ATTRIBUTES = "disabled_attributes"

# List of available providers (Factory mapping will happen in sensor.py)
AVAILABLE_PROVIDERS = {
    "affordableenergy_ca": "Canada (Gas Wizard)",
    "fuelwise_app": "Ontario / GTA (Fuelwise)",
    "citynews_ca": "Canada (CityNews)",
    "globalpetrolprices": "Global API (Key Required)"
}

# Attributes that users can choose to disable in Options Flow
OPTIONAL_ATTRIBUTES = [
    "tomorrow_price", 
    "trend", 
    "effective_date_str", 
    "is_valid", 
    "is_dropping", 
    "is_rising", 
    "provider_name", 
    "city"
]
