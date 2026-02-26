# Mode Timeline with Battery Level — Combined Panel

## What This Panel Shows

A single Grafana Time Series panel that displays:
- **Background**: colored blocks showing which mode is active at each point in time
- **Overlay**: a line showing battery charge percentage over the same time range

The background colors correspond to vessel operational modes (Direct, Idle, Navigation, Station, Voyage), and the battery line is drawn on top with a right-side Y-axis.

## How It Works

### The Trick: Stacked Areas + Line Overlay

Grafana's Time Series panel doesn't natively support "colored background regions". The workaround:

1. **Mode backgrounds** (Query A): Create 5 separate series (one per mode). At each timestamp, the active mode's series has value `100`, all others have value `0`. With `stacking.mode: "normal"` and `stepAfter` interpolation, only the active mode fills the background with its color.

2. **Battery line** (Query B): A standard line series placed in a **separate stacking group** (`group: "B"` with `mode: "none"`), so it floats on top of the stacked backgrounds instead of being stacked with them.

### Why Not State Timeline?

Grafana's State Timeline panel natively shows colored blocks for categorical data. However, it cannot overlay a numeric line series on top. The user needed both mode blocks AND battery % in a single panel, which required the Time Series panel workaround.

## Panel Configuration

### Defaults (applied to all series)
- `drawStyle: "line"` with `lineWidth: 0` and `fillOpacity: 50` — filled areas with no visible line
- `lineInterpolation: "stepAfter"` — sharp transitions between modes (not smooth curves)
- `stacking: {group: "A", mode: "normal"}` — mode series stack to fill 0-100 range
- `min: 0, max: 100` — Y-axis range matches both percentage (battery) and mode fill (100)
- `axisPlacement: "hidden"` — left axis hidden (modes don't need a scale)

### Battery % Override
- `drawStyle: "line"` with `lineWidth: 3` and `fillOpacity: 0` — visible line, no fill
- `lineInterpolation: "smooth"` — smooth curve for battery
- `stacking: {group: "B", mode: "none"}` — NOT stacked (floats independently)
- `axisPlacement: "right"` with label "Battery (%)"
- `color: #0000CC` (bold dark blue)

### Mode Background Overrides
Each mode (Direct, Idle, Navigation, Station, Voyage) has:
- Fixed color matching the project's mode color scheme
- `hideFrom: {tooltip: true}` — hidden from tooltip to reduce clutter

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
  |> filter(fn: (r) => r._measurement == "battery_telemetry")
  |> filter(fn: (r) => r._field == "charge_percentage")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> aggregateWindow(every: 2m, fn: last, createEmpty: false)

union(tables: [
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Direct" then 100.0 else 0.0, _field: "Direct"})) |> group(columns: ["_field"]),
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Idle" then 100.0 else 0.0, _field: "Idle"})) |> group(columns: ["_field"]),
  ... (one per mode)
])
```

**Key points:**
- Uses `battery_telemetry` as the source because it has the `mode` tag and covers the full mission timeline
- `aggregateWindow(every: 2m, fn: last)` downsamples to reduce series density
- Clean `map()` records `({_time, _value, _field})` — avoids metadata leaking into series names
- Each mode series is `group(columns: ["_field"])` so Grafana treats them as separate named series

### Query B — Battery % Line

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "battery_telemetry")
  |> filter(fn: (r) => r._field == "charge_percentage")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _value: r._value * 100.0, _field: "Battery %"}))
  |> group(columns: ["_field"])
```

**Key points:**
- `aggregateWindow(every: 5m, fn: mean)` — smoother line than 2m, reduces noise
- `map(fn: (r) => ({_time: r._time, _value: r._value * 100.0, _field: "Battery %"}))` — MUST use clean records, NOT `({r with ...})`. Using `{r with ...}` preserves metadata columns (_start, _stop, etc.) which leak into the Grafana series name
- `group(columns: ["_field"])` ensures a single series named "Battery %"
- `_value * 100.0` converts from 0-1 fraction to 0-100 percentage

## Tooltip Limitation (Grafana 10.1.2)

The tooltip currently shows only Battery % when hovering. Mode information does not appear because:
- `tooltip.mode: "single"` — only shows the nearest visible series (always Battery %)
- `tooltip.mode: "all"` — breaks completely in Grafana 10.1.2 with this stacked series setup (tooltip disappears entirely)

The mode backgrounds are visible as colors on the chart, and the legend on the right maps colors to mode names. This is sufficient for visual identification of which mode is active.

Upgrading to Grafana 11.x may resolve the tooltip issue, as the tooltip rendering was significantly reworked in that release.

## Reusable Template

Saved as `panel-templates/mode-timeline-with-overlay.json`. To reuse:
1. Copy the JSON into a dashboard's panels array
2. Update datasource UID
3. Replace the Flux queries with your data (keep the same output structure)
4. Update mode names and colors in the overrides
5. Update the overlay series name in the Battery % override matcher
