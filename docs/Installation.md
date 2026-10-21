# Installation

## Via HACS (recommended)

1. Open **HACS** in your Home Assistant sidebar.
2. Search for `Smart Fuel Price`.
3. Click **Download**.
4. Restart Home Assistant Core.

If the integration doesn't show up in the HACS search yet, add it as a
custom repository instead:

1. Open **HACS** in your Home Assistant sidebar.
2. Go to **Integrations**.
3. Click the **⋮** menu (top right) → **Custom repositories**.
4. Add `https://github.com/meokey/smart-fuel-price` with category **Integration**.
5. Search for `Smart Fuel Price` and click **Download**.
6. Restart Home Assistant Core.

## Manual

1. Download `smart_fuel_price.zip` from the latest
   [release](https://github.com/meokey/smart-fuel-price/releases).
2. Extract the `smart_fuel_price` folder to
   `custom_components/smart_fuel_price/` in your Home Assistant config.
3. Restart Home Assistant Core.

## Requirements

- Home Assistant 2024.1 or newer (config-flow based, no YAML needed).
- Internet access — all data comes from public provider websites/APIs.
