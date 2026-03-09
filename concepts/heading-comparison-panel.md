# Heading Comparison Panel

## What It Shows

Two heading sources plotted on the same time-series chart with mode-colored backgrounds:
1. **SBG Ellipse** (red) — IMU-based heading from `/imu/ellipse/sbg_ekf_euler`
2. **AHRS8** (blue) — Attitude and heading reference system from `/imu/ahrs8/data`

Y-axis: 0-360 degrees. Background colors show active vessel mode (same pattern as temperature/humidity panels).

**Note:** GNSS Heading was removed — the `navheading` data showed a constant ~90° value (stuck sensor), so it was not useful for comparison. Only SBG Ellipse and AHRS8 remain.

## Data Sources

| Line | InfluxDB Measurement | Field | Source Topic | Raw Format |
|---|---|---|---|---|
| SBG Ellipse | `ekf_euler` | `heading_degrees` | `/imu/ellipse/sbg_ekf_euler` | Euler angle `yaw` (radians) |
| AHRS8 | `ahrs8` | `heading_degrees` | `/imu/ahrs8/data` | Quaternion orientation |

## Heading Conversion (done at extraction time)

Both sources store heading differently in the raw ROS messages. The conversion to degrees (0-360) is done in `extract-bag.py` during extraction, not in Flux queries.

### Euler → Degrees (SBG Ellipse)

The `sbg_ekf_euler` message has `angle.z` which is yaw in radians:

```python
heading_deg = math.degrees(yaw_rad)
if heading_deg < 0:
    heading_deg += 360.0
```

### Quaternion → Degrees (AHRS8)

`/imu/ahrs8/data` uses `sensor_msgs/msg/Imu` with quaternion orientation:

```python
def quaternion_to_heading_degrees(x, y, z, w):
    yaw_rad = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    heading_deg = math.degrees(yaw_rad)
    if heading_deg < 0:
        heading_deg += 360.0
    return heading_deg
```

## Why `fn: last` Instead of `fn: mean`

Heading values wrap around at the 0°/360° boundary. Using `fn: mean` for aggregation produces **wrong intermediate values** — e.g., averaging 350° and 10° gives 180° (completely wrong). Using `fn: last` preserves actual readings without this wrap-around error.

## How Multiple Lines Work on One Panel

The panel has 3 Flux queries (A, B, C) that all return time-series data into the same panel:

### Query A — Mode Backgrounds

Reads `ekf_euler.heading_degrees` data, checks the `mode` tag, creates 5 series (Direct, Idle, Navigation, Station, Voyage). Uses `v.windowPeriod` for adaptive resolution.

```flux
data = from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "ekf_euler")
  |> filter(fn: (r) => r._field == "heading_degrees")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)

union(tables: [
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Direct" then 100.0 else 0.0, _field: "Direct"})) |> group(columns: ["_field"]),
  ... (one per mode)
])
```

### Queries B, C — Two Heading Lines

Each query follows the same pattern:
1. Read from the respective measurement's `heading_degrees` field
2. Aggregate with `v.windowPeriod` + `fn: last` (preserves actual readings, avoids 0°/360° wrap-around)
3. Rename `_field` to display name using clean `map()` records

```
Query B: ekf_euler → heading_degrees → renamed to "SBG Ellipse"
Query C: ahrs8 → heading_degrees → renamed to "AHRS8"
```

### How Grafana Renders Them Together

All 3 queries return time-series data into the same panel using **stacking groups**:

- Mode series (Query A) in **stacking group "A"** — stacked background fills
- Heading lines (Queries B, C) in **stacking group "B"** with `mode: "none"` — overlay independently

Each line has a field override that matches by name setting color, line width, axis placement, and stacking group. Mode series have `hideFrom.tooltip: true`.

## Panel Configuration

- Type: Time Series
- Mode backgrounds: stacked area series from Query A
- Two overlay lines from Queries B, C (SBG Ellipse red, AHRS8 blue)
- Aggregation: `v.windowPeriod` + `fn: last` for all queries (adaptive resolution, preserves actual readings)
- Tooltip: `mode: "single"` (Grafana 10.1.2 "all" mode broken with stacked series)
- Right Y-axis: Heading (degrees), range 0-360

## Data Volume

| Measurement | Points | ~Per File |
|---|---|---|
| ekf_euler | 1,651,923 | ~2,288 |
| ahrs8 | 1,727,818 | ~2,393 |

AHRS8 and SBG Ellipse publish at ~20 Hz.
