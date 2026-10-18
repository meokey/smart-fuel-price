# Dashboard Cards

Three ready-to-paste Lovelace cards for Smart Fuel Price, inspired by the
[gasbuddy-card](https://github.com/firstof9/gasbuddy-card) design
(header + price tiles + trend sparkline). Replace the example entity IDs
with yours — find them under **☰ → Settings → Tools → States** (they look like
`sensor.smart_fuel_price_gta_tomorrow_s_forecast`).

The examples below use a Gas Wizard GTA device:
- `binary_sensor.smart_fuel_price_gta_buy_now` — the buy-now decision
- `sensor.smart_fuel_price_gta_today_s_price` — today's price
- `sensor.smart_fuel_price_gta_tomorrow_s_forecast` — tomorrow's forecast
- `sensor.smart_fuel_price_gta_last_updated` — last successful fetch

---

## 1. Decision hero (mushroom-template-card)

Big, glanceable: should you fill up today? Requires
[mushroom](https://github.com/piitaya/lovelace-mushroom) (HACS → Frontend).

```yaml
type: custom:mushroom-template-card
entity: binary_sensor.smart_fuel_price_gta_buy_now
primary: >-
  {% if is_state(entity, 'on') %}
    ⛽ Fill up TODAY
  {% elif is_state(entity, 'off') %}
    ⏳ Wait for tomorrow
  {% else %}
    ❓ No forecast data
  {% endif %}
secondary: >-
  {% set d = state_attr(entity, 'price_delta') %}
  {% if d is not none %}
    Tomorrow {{ '+' if d > 0 else '' }}{{ d }}¢/L
  {% endif %}
icon: mdi:fuel
icon_color: >-
  {% if is_state(entity, 'on') %} red
  {% elif is_state(entity, 'off') %} green
  {% else %} grey {% endif %}
tap_action:
  action: more-info
```

The templates use the `entity` variable (the card's own `entity:` field),
so the sensor name appears only once — and in the visual editor that field
is a dropdown, so you can pick the sensor graphically instead of typing it.

## 2. Price detail (markdown)

gasbuddy-card-style price tiles: today vs tomorrow, trend arrow, freshness.

```yaml
type: markdown
content: >-
  {% set today = states('sensor.smart_fuel_price_gta_today_s_price') | float('?') %}
  {% set tomorrow = states('sensor.smart_fuel_price_gta_tomorrow_s_forecast') | float('?') %}
  {% set updated = states('sensor.smart_fuel_price_gta_last_updated') %}
  ### ⛽ GTA — Gas Wizard

  | | Price |
  |---|---|
  | Today | **{{ today }}¢/L** |
  | Tomorrow | **{{ tomorrow }}¢/L** {% if tomorrow is number and today is number %}{% if tomorrow > today %}🔺{% elif tomorrow < today %}🔻{% else %}➖{% endif %}{% endif %} |

  <sub>Updated {{ as_timestamp(updated) | timestamp_custom('%-m/%-d %H:%M') if updated not in ['unknown','unavailable'] else '—' }}</sub>
```

## 3. Trend sparkline (mini-graph-card)

Like gasbuddy-card's `show_trend`: a 7-day price history behind the
current value. Requires
[mini-graph-card](https://github.com/kalkih/mini-graph-card) (HACS → Frontend).
Our price sensors carry `state_class: measurement`, so HA records history
natively — no extra setup.

```yaml
type: custom:mini-graph-card
entities:
  - entity: sensor.smart_fuel_price_gta_tomorrow_s_forecast
    name: Forecast
  - entity: sensor.smart_fuel_price_gta_today_s_price
    name: Today
hours_to_show: 168
points_per_hour: 0.25
line_width: 2
show:
  labels: true
  average: true
```

No mini-graph-card? The built-in `history-graph` works too:

```yaml
type: history-graph
entities:
  - sensor.smart_fuel_price_gta_tomorrow_s_forecast
  - sensor.smart_fuel_price_gta_today_s_price
hours_to_show: 168
```

## 4. Forecast vs NRC reference (history-graph)

Overlay the forecast on the official NRC weekly average — the visual
version of "is today's price high or low?". No entity changes needed:
every price sensor uses ¢/L with `state_class: measurement`, so the
forecast (daily steps) and the NRC average (weekly steps) share one
axis natively. Replace the entity IDs with yours
(☰ → Settings → Tools → States); you need both a forecast device and
an NRC device for the same city.

```yaml
type: history-graph
entities:
  - entity: sensor.smart_fuel_price_toronto_today_s_price
    name: Gas Wizard today
  - entity: sensor.smart_fuel_price_toronto_tomorrow_s_forecast
    name: Gas Wizard tomorrow
  - entity: sensor.smart_fuel_price_toronto_nrc_weekly_average
    name: NRC weekly avg
hours_to_show: 336
```

When the forecast line sits consistently above the NRC line, you're
paying above the official average. The NRC line only moves weekly, so
two weeks (`hours_to_show: 336`) shows about two steps — enough context
without noise.

### Year-long NRC view (backfilled)

The NRC device backfills its full weekly history (~1 year) into HA's
long-term statistics on first fetch, as the external statistic
`smart_fuel_price:nrc_weekly_<city>` (e.g.
`smart_fuel_price:nrc_weekly_toronto`). A `statistics-graph` card shows
the whole year — and overlays the forecast's own recorded history for
the overlapping period:

```yaml
type: statistics-graph
entities:
  - smart_fuel_price:nrc_weekly_toronto
  - sensor.smart_fuel_price_toronto_today_s_price
stat_types:
  - mean
days_to_show: 365
```

(Your sensors' own long-term statistics are recorded automatically by
HA — `state_class: measurement` — so every price and forecast the
integration fetches accumulates history from the day you install it.
The NRC backfill is the special case: it injects the year *before* you
installed, which the recorder could never have seen.)

---

## Blueprint: evening rise alert

Pair the cards with the
[Fuel Price Rise Alert blueprint](../blob/main/blueprints/automation/smart_fuel_price/fuel_price_rise_alert.yaml):
every evening at your chosen time, you get a phone notification when
tomorrow's price is rising. Import it via **Settings → Automations →
Blueprints → Import Blueprint** and paste the raw YAML URL.
