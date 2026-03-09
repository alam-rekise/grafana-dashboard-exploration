# Bar Charts — Battery / Power Consumption

## What These Charts Show

Two bar charts visualizing battery performance per operational mode:

1. **Battery Consumption Rate** — how fast battery drains per hour (%/hour) in each mode
2. **Total Battery Drop %** — how much battery (%) was consumed in each mode across the entire mission

Both read from the **pre-computed `battery_rates` measurement** written by `extract-bag.py` Pass 1b, which uses the exact same algorithm as `mission_time_analysis`.

## Data Source

**InfluxDB measurement**: `battery_rates` (pre-computed by `extract-bag.py` Pass 1b)
- Fields: `rate_pct_per_hour`, `total_drop_pct`, `total_hours`, `total_seconds`, `pairs`
- Tags: `mission`, `vessel`, `mode`
- One point per mode per mission (summary data, stored at epoch timestamps)

**Source data**: `battery_state` measurement (from `/battery_state` ROS topic)
- Field: `percentage` (0-1 range)
- This matches `mission_time_analysis` which uses the `/battery_state` topic

## Why Pre-Computed (not Flux)

### The Flux approach and its limitations

The original Flux queries computed rates at query time using `elapsed+difference+reduce`. This had two fundamental issues:

1. **Cross-mode boundary contamination**: Flux groups by the mode *tag* on each point, then pairs consecutive readings within each group. But two readings tagged with the same mode can span a brief different-mode interruption. The 2s elapsed threshold caught most cases but not all edge cases (e.g., Voyage had 9.21%/hr instead of 9.19%/hr).

2. **Floating-point accumulation order**: Flux's `reduce()` processes rows within mode groups in a different order than Python's chronological iteration, producing slightly different rounding across hundreds of pairs.

### The correct approach (matches mission_time_analysis exactly)

`extract-bag.py` Pass 1b iterates ALL battery readings chronologically and for each consecutive pair:
1. Looks up the mode at **both** timestamps using the mode timeline
2. **Only counts the pair if both readings are in the same mode**
3. Skips pairs where modes differ (even if the readings are tagged with the same mode)

This is identical to `mission_time_analysis`'s `_compute_power_consumption()` method (lines 319-349 of `mission_time_analyzer.py`).

**Result**: All 5 modes now match `mission_time_analysis` exactly:
- Direct: -5.60%/hr (was -5.59 with Flux)
- Idle: 1.05%/hr
- Navigation: 6.42%/hr
- Station: 0.43%/hr
- Voyage: 9.19%/hr (was 9.21 with Flux)

## Flux Queries (simplified — just reads pre-computed values)

### Battery Consumption Rate (%/hour)

```flux
from(bucket: "vessel-data")
  |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "battery_rates")
  |> filter(fn: (r) => r._field == "rate_pct_per_hour")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> filter(fn: (r) => r.mode != "UNKNOWN" and r.mode != "NO_BAG_RECORD" and r.mode != "NO_DATA")
  |> keep(columns: ["mode", "_value"])
  |> group()
  |> rename(columns: {_value: "Rate (%/hour)"})
```

### Total Battery Drop by Mode

```flux
from(bucket: "vessel-data")
  |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "battery_rates")
  |> filter(fn: (r) => r._field == "total_drop_pct")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> filter(fn: (r) => r.mode != "UNKNOWN" and r.mode != "NO_BAG_RECORD" and r.mode != "NO_DATA")
  |> keep(columns: ["mode", "_value"])
  |> group()
  |> rename(columns: {_value: "Battery Drop (%)"})
```

Both use `range(start: 0)` because battery_rates are summary data stored at epoch timestamps.

## Grafana Panel Config

Both charts use the `barchart` panel type with:
- `colorByField` set to the renamed value column
- `color.mode: "continuous-GrYlRd"` — green-yellow-red gradient based on value
- `xField: "mode"` — mode names on X axis
- `showValue: "always"` — values displayed on bars
- `axisLabel` on the left Y-axis ("Rate (%/hour)" or "Battery Drop (%)")

## Reusable Templates

Saved in `panel-templates/`:
- `bar-chart-consumption-rate.json` — consumption rate panel
- `bar-chart-battery-drop.json` — total battery drop panel

Both use `${DS_INFLUXDB}` as datasource UID for portability.
