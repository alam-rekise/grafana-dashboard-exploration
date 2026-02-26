# Bar Charts — Battery / Power Consumption

## What These Charts Show

Two bar charts visualizing battery performance per operational mode:

1. **Total Battery Drop by Mode** — how much battery (%) was consumed in each mode across the entire mission
2. **Battery Consumption Rate by Mode** — how fast battery drains per hour in each mode

Both are panels inside the "Mission mode distribution" dashboard alongside the pie chart and mode timeline.

## Data Source

**InfluxDB measurements** (from ROS bag extraction via `extract-bag.py`):
- `battery_telemetry` — charge_percentage field with mode tag on every point (from `/telemetry/battery_state`)
- `mission_segments` — duration_s per mode segment (from `/control_mode/feedback`)

Previously these charts used CSV-imported `power_consumption` measurement (from `write.js`). That approach had pre-computed summary values (5 rows, one per mode). The current approach computes values dynamically from raw time-series data, which is more accurate and doesn't require re-importing when data changes.

## Flux Queries

### Total Battery Drop by Mode

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "battery_telemetry")
  |> filter(fn: (r) => r._field == "charge_percentage")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> difference(nonNegative: false)
  |> map(fn: (r) => ({r with _value: r._value * -100.0}))
  |> group(columns: ["mode"])
  |> sum()
  |> keep(columns: ["mode", "_value"])
  |> group()
  |> rename(columns: {_value: "Battery Drop (%)"})
```

**Why this query works:**
1. `group() |> sort(columns: ["_time"])` — puts ALL battery readings in chronological order regardless of mode
2. `difference(nonNegative: false)` — computes point-to-point changes (e.g. 0.85 → 0.84 = -0.01)
3. `map(fn: (r) => ({r with _value: r._value * -100.0}))` — converts to positive % (discharge = positive, charge = negative)
4. `group(columns: ["mode"]) |> sum()` — sums all point-to-point drops within each mode

**Why NOT first-to-last per mode:**
The old approach (`reduce` with first/last value per mode group) was wrong because modes are interleaved throughout the mission. For example, Navigation appears in 60 separate segments — first-to-last would span the entire mission duration, not just Navigation segments. The `difference()` approach correctly captures only the actual changes during each mode's active periods.

**Note on mid-mission charging:**
The rosbag-20260223 mission had charging between 14:13 and 23:30 UTC (30,636 points with `is_charging=true`, mostly in Direct mode). This causes Direct mode to show negative battery drop (battery increased). To analyze discharge only, add `|> filter(fn: (r) => r.is_charging != "true")` before the group step.

### Battery Consumption Rate by Mode

```flux
drop = from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "battery_telemetry")
  |> filter(fn: (r) => r._field == "charge_percentage")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> difference(nonNegative: false)
  |> map(fn: (r) => ({r with _value: r._value * -100.0}))
  |> group(columns: ["mode"])
  |> sum()
  |> keep(columns: ["mode", "_value"])
  |> group()

duration = from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "mission_segments")
  |> filter(fn: (r) => r._field == "duration_s")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group(columns: ["mode"])
  |> sum()
  |> map(fn: (r) => ({r with _value: r._value / 3600.0}))
  |> keep(columns: ["mode", "_value"])
  |> group()

join(tables: {drop: drop, duration: duration}, on: ["mode"])
  |> map(fn: (r) => ({r with _value: r._value_drop / r._value_duration}))
  |> keep(columns: ["mode", "_value"])
  |> rename(columns: {_value: "Rate (%/hour)"})
```

**Why this query uses join instead of reduce:**
The old `reduce`-based approach computed rate inline using `(first_val - last_val) / (last_time - first_time)`. This had two issues:
1. Same first-to-last problem as battery drop (spans entire mission per mode)
2. Nanosecond timestamp arithmetic in Flux is fragile and produced tiny unreadable values (0.0332 instead of 3.32)

The join approach:
- `drop`: total battery change per mode (same as battery drop query)
- `duration`: total time in each mode from `mission_segments` (in hours)
- Join on mode, divide drop by hours → clean readable %/hour values

## Key Flux Patterns

- `difference(nonNegative: false)` — point-to-point changes; `false` allows negative values (charging)
- `rename(columns: {_value: "..."})` — replaces the default `_value` legend label with something readable
- `keep(columns: ["mode", "_value"])` — strips all metadata, leaving only what the chart needs
- `join(tables: {a: a, b: b}, on: ["key"])` — merges two queries; produces `_value_a` and `_value_b` columns
- `${mission}` — template variable from the Mission dropdown

## Grafana Panel Config

Both charts use the `barchart` panel type with:
- `colorByField` set to the renamed value column (e.g. "Battery Drop (%)")
- `color.mode: "continuous-GrYlRd"` — green-yellow-red gradient based on value
- `xField: "mode"` — mode names on X axis
- `showValue: "always"` — values displayed on bars

## Reusable Templates

Saved in `panel-templates/`:
- `bar-chart-battery-drop.json` — total battery drop panel
- `bar-chart-consumption-rate.json` — consumption rate panel

Both use `${DS_INFLUXDB}` as datasource UID for portability. Copy into any dashboard and update the bucket, measurement, field, and mission filter in the queries.
