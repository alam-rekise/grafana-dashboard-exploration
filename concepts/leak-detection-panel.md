# Leak Detection Panel

## What It Shows

Leak sensor status over time with mode-colored backgrounds. The panel displays the state of the pico leak detector across all 722 missions, using a **two-series split** to visually distinguish normal operation from leak events:

- **No Leak** (green dots) — status == 0, normal operation
- **Leak Detected** (red dots) — status > 0, leak event detected

The status values are:
- **0** = No Leak
- **1** = Sensor A - Back
- **2** = Sensor B - Front
- **3** = Both Sensors

This matches the visual style of `mission_time_analysis` charts where leak events are highlighted in red.

## Data Sources

| Component | InfluxDB Measurement | Field | Source Topic | Raw Format |
|---|---|---|---|---|
| Leak Status | `leak_detect` | `status` | `/leak_detect` | rkse_common_interfaces/msg/LeakStatus (int) |
| Mode Backgrounds | `leak_detect` | `status` | `/leak_detect` | (uses mode tag) |

## Data Collection

The pico leak detector publishes status updates to `/leak_detect`. Across 722 bag files (68 GB):

- **Total leak_detect points**: 84,616
- **Average per file**: ~117 points
- **Actual status values observed**: 0 and 1 only
  - No instances of Sensor B (value 2) or Both Sensors (value 3)
  - At least one "Sensor A - Back" event (value 1) occurred during missions

## How the Panel Works

The panel has 3 Flux queries (A, B, C):

### Query A — Mode Backgrounds

Reads `leak_detect.status` data and creates 5 mode series. Uses `v.windowPeriod` + `fn: last` for adaptive resolution.

```flux
data = from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "leak_detect")
  |> filter(fn: (r) => r._field == "status")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)

union(tables: [
  data |> map(...) -- one per mode (Direct, Idle, Navigation, Station, Voyage)
])
```

### Query B — No Leak (green dots)

Filters for status == 0 and shows as green dots. Uses `fn: max` to ensure brief leaks within an aggregation window aren't hidden.

```flux
from(bucket: "vessel-data")
  |> filter(fn: (r) => r._measurement == "leak_detect")
  |> filter(fn: (r) => r._field == "status")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)
  |> filter(fn: (r) => r._value == 0)
  |> map(fn: (r) => ({_time: r._time, _value: float(v: r._value), _field: "No Leak"}))
  |> group(columns: ["_field"])
```

### Query C — Leak Detected (red dots)

Filters for status > 0 and shows as red dots. Uses `fn: max` so brief leaks that occur within an aggregation window are preserved (not averaged away to 0).

```flux
from(bucket: "vessel-data")
  |> filter(fn: (r) => r._measurement == "leak_detect")
  |> filter(fn: (r) => r._field == "status")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)
  |> filter(fn: (r) => r._value > 0)
  |> map(fn: (r) => ({_time: r._time, _value: float(v: r._value), _field: "Leak Detected"}))
  |> group(columns: ["_field"])
```

### Why `fn: max` for Leak Detection

Using `fn: last` could miss brief leak events that occur mid-window but clear before the window end. Using `fn: max` ensures the highest status in any aggregation window is preserved — if any leak occurred during the window, max will catch it.

## Panel Configuration

- Type: Time Series
- Mode backgrounds: stacked area series from Query A
- **No Leak** series (Query B): green (#56A64B), `showPoints: "always"`, `pointSize: 5`, `fillOpacity: 30`, `lineWidth: 0`
- **Leak Detected** series (Query C): red (#F2495C), `showPoints: "always"`, `pointSize: 10`, `fillOpacity: 100`, `lineWidth: 0`
- Both leak series: stacking group "B" mode "none", stepAfter interpolation
- Aggregation: `v.windowPeriod` for all queries (adaptive resolution)
- Tooltip: `mode: "single"` (Grafana 10.1.2 "all" mode broken with stacked series)
- Right Y-axis: Status, range 0-3

## Why Two Series Instead of One

The previous approach used a single green line for all leak status values. Splitting into two series (No Leak + Leak Detected) provides:
1. **Visual alarm**: Red dots immediately draw attention to leak events
2. **Consistency**: Matches the `mission_time_analysis` chart style where leaks are highlighted in red
3. **Different dot sizes**: Leak events use larger dots (pointSize: 10) for emphasis

## Data Volume

| Measurement | Points | ~Per File |
|---|---|---|
| leak_detect | 84,616 | ~117 |

The leak detector publishes infrequently compared to high-frequency sensors. This is normal for event-driven sensors.
