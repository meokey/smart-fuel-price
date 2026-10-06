"""Constants for the Smart Fuel Price integration."""

DOMAIN = "smart_fuel_price"
DEFAULT_NAME = "Tomorrow Fuel Price Change"

CONF_PROVIDER = "provider"
CONF_CITY = "city"
CONF_API_KEY = "api_key"
CONF_DISABLED_ATTRIBUTES = "disabled_attributes"
CONF_STATION_IDS = "station_ids"
CONF_CACHE_TTL_MINUTES = "cache_ttl_minutes"

# Preset cache TTLs (minutes) per provider -- editable per config entry in
# the Options flow. Forecast sources publish ~daily, so 4h keeps polls
# gentle; GasBuddy is a live map, 30 min matches its previous cadence.
DEFAULT_CACHE_TTL_MINUTES = {
    "affordableenergy_ca": 240,
    "citynews_ca": 240,
    "gasbuddy_ca": 30,
    "fuelwise_app": 240,
}

CONF_FUEL_GRADES = "fuel_grades"
GASBUDDY_FUEL_GRADES = {
    "regular": "Regular",
    "midgrade": "Midgrade",
    "premium": "Premium",
    "diesel": "Diesel",
}

# List of available providers (Factory mapping will happen in sensor.py)
AVAILABLE_PROVIDERS = {
    "affordableenergy_ca": "Canada (Gas Wizard)",
#    "fuelwise_app": "Ontario / GTA (Fuelwise)",
    "citynews_ca": "Canada (CityNews)",
    "gasbuddy_ca": "GasBuddy (Station)"
}

# Attributes that users can choose to disable in Options Flow
OPTIONAL_ATTRIBUTES = [
    "tomorrow_price",
    "current_price",
    "trend", 
    "effective_date_str", 
    "is_valid", 
    "is_dropping", 
    "is_rising", 
    "provider_name", 
    "city",
    "station_id",
    "station_name",
    "address",
    "province_or_state",
    "last_reported_str",
    "from_cache",
    "stale",
]
