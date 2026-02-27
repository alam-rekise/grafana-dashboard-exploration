# Heading Comparison Panel

## What It Shows

Three heading sources plotted on the same time-series chart with mode-colored backgrounds:
1. **SBG Ellipse** (red) — IMU-based heading from `/imu/ellipse/sbg_ekf_euler`
2. **AHRS8** (blue) — Attitude and heading reference system from `/imu/ahrs8/data`
3. **GNSS Heading** (green) — GPS-based heading from `/moving_base_second/navheading`

Y-axis: 0-360 degrees. Background colors show active vessel mode (same pattern as temperature/humidity panels).

## Data Sources

| Line | InfluxDB Measurement | Field | Source Topic | Raw Format |
|---|---|---|---|---|
| SBG Ellipse | `ekf_euler` | `heading_degrees` | `/imu/ellipse/sbg_ekf_euler` | Euler angle `yaw` (radians) |
| AHRS8 | `ahrs8` | `heading_degrees` | `/imu/ahrs8/data` | Quaternion orientation |
| GNSS Heading | `navheading` | `heading_degrees` | `/moving_base_second/navheading` | Quaternion orientation |

## Heading Conversion (done at extraction time)

All three sources store heading differently in the raw ROS messages. The conversion to degrees (0-360) is done in `extract-bag.py` during extraction, not in Flux queries. This keeps the Flux queries simple.

### Euler → Degrees (SBG Ellipse)

The `sbg_ekf_euler` message has `angle.z` which is yaw in radians:

```python
heading_deg = math.degrees(yaw_rad)
if heading_deg < 0:
    heading_deg += 360.0
```

### Quaternion → Degrees (AHRS8, GNSS)

Both `/imu/ahrs8/data` and `/moving_base_second/navheading` use `sensor_msgs/msg/Imu` with quaternion orientation:

```python
def quaternion_to_heading_degrees(x, y, z, w):
    yaw_rad = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    heading_deg = math.degrees(yaw_rad)
    if heading_deg < 0:
        heading_deg += 360.0
    return heading_deg
```

This is the standard quaternion-to-yaw (heading) conversion. The `atan2` extracts the yaw component from the quaternion, and the normalization ensures the result is always in the 0-360 range.

## Why Convert at Extraction Time?

Doing the conversion in Flux queries would be complex:
- Quaternion conversion requires multiple fields in the same row (x, y, z, w) — needs a `pivot()` operation
- Flux's `math.atan2()` works but the full expression is verbose and error-prone
- Pre-computed `heading_degrees` fields make all future queries simple: just filter by `_field == "heading_degrees"`

## How Multiple Lines Work on One Panel

The panel has 4 Flux queries (A, B, C, D) that all return time-series data into the same panel:

### Query A — Mode Backgrounds

Reads `ekf_euler.heading_degrees` data, checks the `mode` tag on each data point, and creates 5 series (Direct, Idle, Navigation, Station, Voyage). Each series is either 100 (active) or 0 (inactive) at that timestamp. These get stacked as filled areas, creating the colored backgrounds.

### Queries B, C, D — The Three Heading Lines

Each query follows the same pattern:
1. Read from the respective measurement's `heading_degrees` field
2. Aggregate to 5-minute mean (smooths the data, reduces points)
3. Rename the `_field` to the display name

```
Query B: ekf_euler → heading_degrees → renamed to "SBG Ellipse"
Query C: ahrs8 → heading_degrees → renamed to "AHRS8"
Query D: navheading → heading_degrees → renamed to "GNSS Heading"
```

### How Grafana Renders Them Together

All 4 queries return time-series data into the same panel. The key is **stacking groups**:

- The mode series (from query A) are in **stacking group "A"** — they stack on top of each other to fill the background
- The three heading lines are in **stacking group "B"** with `mode: "none"` — they overlay independently on top of the backgrounds without stacking with each other

Each line has a field override that matches by name (e.g., `byName: "SBG Ellipse"`) which sets its color, line width, axis placement, and stacking group. The mode series have overrides that hide them from the tooltip (`hideFrom.tooltip: true`) so hovering only shows the heading values.

This is the same reusable pattern from the temperature and humidity panels, just with 3 overlay lines instead of 1.

## Panel Configuration

- Type: Time Series (same template as temperature/humidity panels)
- Mode backgrounds: stacked area series from query A (100 or 0 per mode)
- Three overlay lines from queries B, C, D (one per heading source)
- Aggregation: 2m intervals for backgrounds, 5m mean for lines
- Tooltip: `mode: "single"` (Grafana 10.1.2 "all" mode is broken with stacked series)
- Right Y-axis: Heading (degrees), range 0-360

## Data Volume

| Measurement | Points | ~Per File |
|---|---|---|
| ekf_euler | 1,651,923 | ~2,288 |
| ahrs8 | 1,727,818 | ~2,393 |
| navheading | 418,016 | ~579 |

AHRS8 and SBG Ellipse publish at ~20 Hz. GNSS heading publishes at ~5 Hz (lower resolution GPS data).
