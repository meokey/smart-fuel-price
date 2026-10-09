Implements the Calgary half of #30 -- the other markets (Van/Edm/Win/Mtl/Hal) still need layout verification.

## How it works (no JS execution)

Bill's DevTools inspection found the key: the page embeds GasBuddy
`feed.gdf` script tags, and the browser's second request returns
JavaScript that writes the price straight into the DOM
(`getElementById('price126610').innerHTML='169.1'`). So:

1. GET the CityNews gas-prices page, extract the `feed.gdf` script tags
   (HTML-unescaped).
2. Replay the browser's request per tag (`&url=<page>` appended, Referer
   set).
3. Regex the price/city/trend assignments; first feed with a price wins.

Verified live from the VM: `169.1` (matches Bill's screenshot), trend
falling.

## Changes

- `vendor_widgets.parse_gasbuddy_report(page_html, page_url, get)` --
  rewritten for the two-step fetch (was a parked stub).
- `citynews_ca.py` -- wires the parser; parser-aware URL candidate order
  (Calgary's plain `gas-prices/` soft-404s to a 2013 article with HTTP 200,
  so `{subdomain}-gas-prices/` goes first for the gasbuddy layout);
  `sensor_name` -> "Current Average Price" and
  `allow_stale_on_failure=True` for the gasbuddy layout (it reports a
  current average, not a forecast change).
- Tests: rewritten widget tests + new Calgary end-to-end (FakeSession
  two-step). **81 passed**, 2 skipped, 10 deselected (live).
- README: Calgary listed as supported (current average via GasBuddy
  widget, no forecast).

## Test report

- `pytest`: 81 passed, 2 skipped, 10 deselected (live/ha_integration
  excluded per pytest.ini).
- Live probe (read-only): `CityNewsCaProvider('calgary').get_data()` ->
  is_valid True, state 169.1, trend falling; Toronto regression-checked
  (Price Change, no stale).
