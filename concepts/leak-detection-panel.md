# Leak Detection Panel

## What It Shows

Leak sensor status over time with mode-colored backgrounds. The panel displays the state of the pico leak detector across all 722 missions, showing when and where leaks were detected.

The status line (green) shows:
- **0** = No Leak
- **1** = Sensor A - Back
- **2** = Sensor B - Front
- **3** = Both Sensors

A green horizontal line indicates active monitoring, stepping up/down when the status changes. The colored background regions show which vessel mode was active at each timestamp.

Y-axis: 0-3 (fixed range with custom tick spacing to show all 4 status values).

## Data Sources

| Component | InfluxDB Measurement | Field | Source Topic | Raw Format |
|---|---|---|---|---|
| Leak Status Line | `leak_detect` | `status` | `/leak_detect` | rkse_common_interfaces/msg/LeakStatus (int) |
| Mode Backgrounds | `ekf_euler` | `heading_degrees` | `/imu/ellipse/sbg_ekf_euler` | Euler angle yaw (radians) |

The leak status values are stored as integers in the `leak_detect` measurement. The mode information comes from the `ekf_euler` measurement's `mode` tag (same tag used by temperature/humidity panels).

## Data Collection

The pico leak detector publishes status updates to `/leak_detect` whenever the sensor state changes or at regular intervals. Across 722 bag files (68 GB):

- **Total leak_detect points**: 84,616
- **Average per file**: ~117 points
- **Actual status values observed**: 0 and 1 only
  - No instances of Sensor B (value 2) or Both Sensors (value 3)
  - At least one "Sensor A - Back" event (value 1) occurred during missions
  - This suggests the back leak sensor may be more sensitive or positioned to detect water ingress earlier

## Value Mapping in Grafana

Grafana converts the numeric status values to human-readable text using value mappings:

```
0 → "No Leak"
1 → "Sensor A - Back"
2 → "Sensor B - Front"
3 → "Both Sensors"
```

These mappings are configured in the panel's field overrides for the leak status series. The display always shows the text label, while the Y-axis tick values remain 0, 1, 2, 3.

## How Multiple Series Work on One Panel

The panel has 2 Flux queries (A, B) that render together:

### Query A — Mode Backgrounds

Reads `ekf_euler.heading_degrees` data and extracts the `mode` tag. Creates 5 series (Direct, Idle, Navigation, Station, Voyage). Each series shows 100 when the mode is active, 0 otherwise. These stack as filled areas creating the colored backgrounds.

### Query B — Leak Status Line

Reads `leak_detect.status` field and renames it to "Leak Status". Returns the raw integer values (0-3) as a line series. Uses step interpolation (`stepAfter`) so the line jumps between discrete states instead of interpolating.

### How Grafana Renders Them Together

Both queries return time-series data into the same panel using **stacking groups**:

- The mode series (from query A) are in **stacking group "A"** — they stack to form the background
- The leak status line (from query B) is in **stacking group "B"** with `mode: "none"` — it overlays independently on top without stacking

The leak status series has a field override that sets:
- Color: green (#56A64B)
- Line width: 2
- Draw style: line
- Line interpolation: stepAfter
- Value mappings: 0→"No Leak", 1→"Sensor A - Back", 2→"Sensor B - Front", 3→"Both Sensors"

The mode series have overrides that hide them from tooltips (`hideFrom.tooltip: true`) so hovering shows only the leak status, not the mode values.

This follows the same reusable pattern as the temperature and humidity panels.

## Panel Configuration

- Type: Time Series
- Mode backgrounds: stacked area series from query A
- Leak status line: step-interpolated line from query B
- Aggregation: 2m intervals for backgrounds, no aggregation for leak status (uses raw data points)
- Tooltip: `mode: "single"` (Grafana 10.1.2 "all" mode is broken with stacked series)
- Right Y-axis: Status, range 0-3 with 5 ticks (0.0, 1.0, 2.0, 3.0 at custom intervals)
- Step interpolation: stepAfter (discrete steps between status values)

## Why Step Interpolation?

The leak detector returns discrete integer status values (0, 1, 2, or 3). Linear interpolation would create false intermediate values between states. Step interpolation (`stepAfter`) keeps the value constant until the next data point, accurately representing the detector's discrete state changes.

For example, transitioning from "No Leak" (0) to "Sensor A - Back" (1):
- **With linear interpolation**: the line would tilt, suggesting brief intermediate values that never actually occurred
- **With step interpolation**: the line stays flat at 0, then jumps to 1, accurately showing the state change was instantaneous

## Integration with Mission Timeline

The leak detection panel (Panel 8) sits alongside the mode+battery timeline and other sensor panels in the dashboard. The mode-colored backgrounds create visual alignment across all time-series panels, making it easy to correlate leak events with specific mission phases (Direct, Idle, Navigation, Station, or Voyage).

For example, if a leak is detected during a Navigation phase, the background will be blue and the leak status line will step up to 1 or higher.

## Data Volume

| Measurement | Points | ~Per File |
|---|---|---|
| leak_detect | 84,616 | ~117 |

The leak detector publishes infrequently compared to high-frequency sensors like IMU (ekf_euler: ~2,288 points/file) or AHRS8 (~2,393 points/file). This is normal for event-driven sensors — status updates occur mainly when the sensor state changes or at periodic check intervals.
