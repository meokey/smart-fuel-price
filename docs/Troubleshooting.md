# Troubleshooting

**A sensor shows "Unknown".**
Check the device's **Last updated** and **Update status** sensors first.
Right after a restart the first fetch can take one poll cycle; the
persisted cache (`.storage`) normally covers the gap. Forecast providers
show `unknown` — never stale data — until the source publishes fresh
numbers; Gas Wizard's tomorrow forecast is usually out by the evening.

**Update status says "Rate limited".**
The source is throttling requests. Sensors keep working from cache
(GasBuddy marks it `stale: True`). Follow the `suggestion` attribute:
raise the **cache threshold** for that entry (gear icon → Configure).

**The entity list says "updated X minutes ago" but the data looks old.**
That text is Home Assistant's `last_changed`, which resets whenever the
entity is re-created (restart, options change) — not a freshness signal.
Trust the **Last updated** sensor instead.

**GasBuddy flips between OK and "Rate limited".**
GasBuddy occasionally challenges automated requests (Cloudflare). The
integration retries with a fresh session token; brief flapping during
such episodes is expected and resolves on its own.

**Prices look wrong vs. the source site.**
Open the device info card's source link to compare directly. If the site
changed its layout, please file a [bug report](https://github.com/meokey/smart-fuel-price/issues/new/choose)
— include the provider, city/station, and what you saw.
