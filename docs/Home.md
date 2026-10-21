<p align="center">
  <img src="https://raw.githubusercontent.com/meokey/smart-fuel-price/main/custom_components/smart_fuel_price/brand/logo.png" alt="Smart Fuel Price — tomorrow's predictions today" width="600" />
</p>

Know **tomorrow's** fuel price **today** — and whether to fill up now or wait.
Smart Fuel Price is a Home Assistant custom integration tracking Canadian
fuel prices across four read-only sources (see
[Providers](https://github.com/meokey/smart-fuel-price/wiki/Providers)):

- **Gas Wizard** — daily forecast per city: today's price + tomorrow's predicted price
- **CityNews** — daily price-change forecasts for major cities
- **GasBuddy** — live per-station prices for any station, per fuel grade
- **NRC Weekly** — Natural Resources Canada's official weekly average per city: a reference anchor for judging whether today's price is high or low

Why it's useful:

- **Buy-now sensor** — a binary sensor that answers the real question directly: fill up today, or wait for tomorrow
- **Honest status** — *Update status* and *Last updated* sensors always tell the truth about data freshness
- **Polite by design** — cached polling, one fetch per provider on manual refresh, read-only sources that never get hammered

New here? Start with
[Installation](https://github.com/meokey/smart-fuel-price/wiki/Installation).
Building dashboards? See
[Dashboard cards](https://github.com/meokey/smart-fuel-price/wiki/Dashboard-cards).
Contributing a source? See
[Developing a new provider](https://github.com/meokey/smart-fuel-price/wiki/Developing-a-new-provider).

Elsewhere:

- Project README: https://github.com/meokey/smart-fuel-price
- Bug reports & feature requests: https://github.com/meokey/smart-fuel-price/issues
- Changelog: https://github.com/meokey/smart-fuel-price/releases
