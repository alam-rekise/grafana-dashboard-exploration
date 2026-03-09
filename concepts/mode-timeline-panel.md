# Mode Timeline with Battery Level — Combined Panel

## What This Panel Shows

A single Grafana Time Series panel that displays:
- **Background**: colored blocks showing which mode is active at each point in time
- **Overlay**: a line showing battery charge percentage over the same time range
- **Tooltip**: hovering shows Battery % value and current mode name (via Query C)

The background colors correspond to vessel operational modes (Direct, Idle, Navigation, Station, Voyage), and the battery line is drawn on top with a right-side Y-axis.

## Data Source

**InfluxDB measurement**: `battery_state` (from `/battery_state` ROS topic)
- Field: `percentage` (0-1 range, multiplied by 100 for display)
- This matches `mission_time_analysis` which uses the `/battery_state` topic
- Note: `battery_telemetry.charge_percentage` has identical values but different publish rate

## How It Works

### The Trick: Stacked Areas + Line Overlay

Grafana's Time Series panel doesn't natively support "colored background regions". The workaround:

1. **Mode backgrounds** (Query A): Create 5 separate series (one per mode). At each timestamp, the active mode's series has value `100`, all others have value `0`. With `stacking.mode: "normal"` and `stepAfter` interpolation, only the active mode fills the background with its color.

2. **Battery line** (Query B): A standard line series placed in a **separate stacking group** (`group: "B"` with `mode: "none"`), so it floats on top of the stacked backgrounds.

3. **Mode tooltip** (Query C): A hidden numeric series that maps modes to numbers (1-5). The tooltip shows this as the mode name via value mappings. This works around the limitation that mode background series are hidden from tooltips.

## Panel Configuration

### Defaults (applied to all series)
- `drawStyle: "line"` with `lineWidth: 0` and `fillOpacity: 50` — filled areas with no visible line
- `lineInterpolation: "stepAfter"` — sharp transitions between modes
- `stacking: {group: "A", mode: "normal"}` — mode series stack to fill 0-100 range
- `min: 0, max: 100` — Y-axis range matches both percentage and mode fill
- `axisPlacement: "hidden"` — left axis hidden

### Battery % Override
- `drawStyle: "line"` with `lineWidth: 3` and `fillOpacity: 0` — visible line, no fill
- `lineInterpolation: "smooth"` — smooth curve for battery
- `stacking: {group: "B", mode: "none"}` — NOT stacked (floats independently)
- `axisPlacement: "right"` with label "Battery (%)"
- `color: #0000CC` (bold dark blue)

### Mode Background Overrides
Each mode has fixed color + `hideFrom: {tooltip: true}`.

### Mode Colors
| Mode | Color | Hex |
|------|-------|-----|
| Direct | Light blue | #73BFF2 |
| Idle | Gray | #B0B0B0 |
| Navigation | Dark purple | #8F3BB8 |
| Station | Bright purple | #C840E9 |
| Voyage | Blue | #3274D9 |
| Battery % line | Bold dark blue | #0000CC |

## Queries

### Query A — Mode Backgrounds

```flux
data = from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "battery_state")
  |> filter(fn: (r) => r._field == "percentage")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)

union(tables: [
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Direct" then 100.0 else 0.0, _field: "Direct"})) |> group(columns: ["_field"]),
  ... (one per mode)
])
```

### Query B — Battery % Line

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "battery_state")
  |> filter(fn: (r) => r._field == "percentage")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _value: r._value * 100.0, _field: "Battery %"}))
  |> group(columns: ["_field"])
```

### Query C — Mode Tooltip

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "battery_state")
  |> filter(fn: (r) => r._field == "percentage")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Direct" then 1.0 else if r.mode == "Idle" then 2.0 else if r.mode == "Navigation" then 3.0 else if r.mode == "Station" then 4.0 else if r.mode == "Voyage" then 5.0 else 0.0, _field: "Mode"}))
  |> group(columns: ["_field"])
```

**Key points:**
- All queries use `v.windowPeriod` for adaptive resolution (adjusts based on zoom level and panel width)
- `fn: last` preserves actual values without smoothing/averaging
- Clean `map()` records `({_time, _value, _field})` — avoids metadata leaking into series names
- `_value * 100.0` converts from 0-1 fraction to 0-100 percentage

## Adaptive Resolution with `v.windowPeriod`

Previous queries used hardcoded intervals (`2m` for backgrounds, `5m` for battery line). This caused:
- Too few points when zoomed in → missing mode transitions
- Too many points when zoomed out → "too many datapoints" errors

`v.windowPeriod` is Grafana's built-in variable that adapts based on the time range and panel width (~1830 max datapoints). Combined with `fn: last` (not `fn: mean`), it preserves actual readings at the resolution the panel can display.

## Tooltip Limitation (Grafana 10.1.2)

- `tooltip.mode: "single"` — only shows the nearest visible series
- `tooltip.mode: "all"` — breaks completely with stacked series (tooltip disappears)
- Query C provides mode information in tooltip via value mappings

## Reusable Template

Saved as `panel-templates/mode-timeline-with-overlay.json`. To reuse:
1. Copy the JSON into a dashboard's panels array
2. Update datasource UID
3. Replace the Flux queries with your data (keep same output structure)
4. Update mode names and colors in overrides
5. Update the overlay series name in the Battery % override matcher
