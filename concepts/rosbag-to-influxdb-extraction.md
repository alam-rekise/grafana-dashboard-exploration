# ROS Bag → InfluxDB Direct Extraction

## Why Direct Extraction?
The original pipeline was: ROS bag → Python script → Excel → CSV → write.js → InfluxDB.
Problem: the Excel step does not carry over proper timestamps, which are required for time-series visualization in Grafana.
Solution: bypass Excel entirely — read ROS bag directly and write to InfluxDB.

## How It Works

### Tools Used
- **rosbags** (v0.11.0): pure Python library for reading ROS2 .db3 bag files — no ROS2 installation needed
- **influxdb-client**: Python client for writing to InfluxDB
- **typestore API**: from rosbags, handles message deserialization including custom message types

### The Two-Pass Approach

**Pass 1 — Build Mode Timeline (parallelized):**
1. Scan all bag files in parallel (16 workers) to collect:
   - Bag intervals (start_time, end_time from `reader.start_time`/`reader.end_time`)
   - `/control_mode/feedback` messages (~411 across 722 files)
2. Compute **recording sessions** — merge adjacent bags (gap < 2s = same session)
3. Build raw segments (new segment only when mode changes)
4. **Extend segments to session boundaries** — since feedback only publishes on MODE CHANGE, extend first segment back to session start, last forward to session end
5. **Split segments at session boundaries** — split segments spanning multiple sessions
6. **Insert gap segments** — NO_DATA (within session, no feedback) and NO_BAG_RECORD (between sessions)
7. **Merge consecutive** same-mode segments
8. Write as `mission_segments` measurement to InfluxDB

This matches `mission_time_analysis`'s `ModeSegmentExtractor` behavior (boundary extension, gap filling, segment splitting).

**Important:** `/control_mode/status` (KeyValue[] array) was initially used but always reported "Idle".
The correct mode source is `/control_mode/feedback` with `current_mode_name`.

**Pass 1b — Pre-Compute Battery Rates per Mode (parallelized):**
1. Scan all bags in parallel (16 workers) to collect battery_state readings
2. Sort all readings chronologically
3. Iterate consecutive pairs, check mode at BOTH timestamps via mode timeline
4. Only count pair if both readings are in the same mode (matches mission_time_analysis's `_compute_power_consumption()`)
5. Accumulate total_drop and total_seconds per mode
6. Write as `battery_rates` measurement to InfluxDB (one point per mode)

This ensures battery bar charts match mission_time_analysis exactly — Flux's group-by-mode approach can't replicate the chronological dual-timestamp mode check.

**Pass 2 — Process All Sensor Topics (16 workers):**
1. Each worker opens one bag file, iterates all messages
2. For each message:
   - Deserialize using typestore
   - Flatten nested fields (e.g. SbgEkfEuler.angle.x → roll)
   - Look up which mode was active at that timestamp (binary search on mode timeline)
   - Create InfluxDB Point with tags: mission, vessel, mode
3. Batch write to InfluxDB per topic (flush every 5000 points)

### Mode Lookup (Binary Search)
Every sensor reading gets tagged with the mode active at its timestamp.
Uses `bisect_right` for O(log n) lookup with upper-bound check.
Edge cases:
- Timestamp before first recording session → tagged as "UNKNOWN"
- Timestamp after last segment end → tagged as "UNKNOWN"
- Timestamp in NO_BAG_RECORD gap → tagged as "NO_BAG_RECORD"

### Custom Message Type Registration
ROS2 bags from Rekise use custom message types (rkse_common_interfaces, rkse_telemetry_interfaces, etc.)
that the standard typestore doesn't know about.

The rosbags library needs these registered before it can deserialize messages:
```python
from rosbags.typesys.msg import get_types_from_msg

custom_msg_defs = [
    ("rkse_common_interfaces/msg/ControlModeFeedback",
     "std_msgs/Header header\nstring manual_preset_name\n"
     "string stationary_preset_name\nstring current_mode_name\n"
     "uint8 current_mode\nbuiltin_interfaces/Duration duration"),
    # ... more custom types
]

all_types = {}
for msgtype, msgdef in custom_msg_defs:
    all_types.update(get_types_from_msg(msgdef, msgtype))
typestore.register(all_types)
```

## Data Structure in InfluxDB

### Tags (indexed, for filtering)
- **mission**: e.g. "rosbag-20260223-v2" — separates data per bag/mission
- **vessel**: e.g. "AUV_01"
- **mode**: e.g. "Idle", "Navigation", "Direct", "Station", "Voyage", "NO_BAG_RECORD", "UNKNOWN"

### Measurements Written (17 total)

| Measurement | Source Topic | Key Fields |
|---|---|---|
| mission_segments | /control_mode/feedback | duration_s, start_time_ns, end_time_ns, segment_number |
| battery_rates | /battery_state (pre-computed) | rate_pct_per_hour, total_drop_pct, total_hours, total_seconds, pairs |
| battery_state | /battery_state | voltage, current, charge, percentage, temperature |
| temperature | /temperature | temperature_c |
| humidity | /humidity | relative_humidity |
| pressure | /pressure | fluid_pressure |
| odometry | /odometry/filtered | position x/y/z, orientation, linear/angular velocity |
| navheading | /moving_base_second/navheading | orientation quaternion, angular velocity, heading_degrees |
| gnss | /gnss/fix | latitude, longitude, altitude, status |
| vessel_mode | /vessel/mode | value (0=STAGING, 1=ACTIVE) |
| telemetry_state | /telemetry/state | lat, lon, heading, depth, altitude, speed, course, yaw_rate |
| battery_telemetry | /telemetry/battery_state | voltage, charge_percentage, is_charging, error_code |
| pack_status | /pack_status | 17 fields (soc, voltage, current, health, etc.) |
| power_mgmt | /pm/feedback | 23 fields (load_current, bus_voltage, temperature, etc.) |
| leak_detect | /leak_detect | status |
| ekf_euler | /imu/ellipse/sbg_ekf_euler | roll, pitch, yaw, heading_degrees, accuracy, 15 status flags |
| ahrs8 | /imu/ahrs8/data | orientation quaternion, angular velocity, heading_degrees |

### Why Mode as a Tag on Every Point?
This enables maximum Grafana flexibility:
- Filter ANY measurement by mode: `filter(fn: (r) => r.mode == "Navigation")`
- Group ANY measurement by mode for per-mode bar charts
- Overlay any data on top of mode timeline
- No Flux joins needed — mode info is already on each point

## Usage

```bash
# Dry run — single file
python3 extract-bag.py --mission test-001 --bag /path/to/file.db3 --dry-run

# Full extraction — 16 parallel workers
python3 extract-bag.py --mission rosbag-20260223-v2 --bag-dir /path/to/rosbags/ --force --workers 16

# Sequential (1 worker, useful for debugging)
python3 extract-bag.py --mission rosbag-20260223 --bag /path/to/file.db3
```

### Performance (722 files, 68 GB, 9.85M points)
- Pass 1 (parallel scan): ~60s
- Pass 2 (16 workers): ~130s
- **Total: ~3.3 minutes**

## Grafana Queries for ROS Bag Data

### Mode Distribution (Pie Chart)
Uses `range(start: 0)` to capture ALL segments regardless of dashboard time range.
Excludes NO_DATA, includes NO_BAG_RECORD (matches mission_time_analysis).
Unit: `dthms` (displays as hours:minutes).
```flux
from(bucket: "vessel-data")
  |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "mission_segments")
  |> filter(fn: (r) => r._field == "duration_s")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> filter(fn: (r) => r.mode == "Direct" or r.mode == "Idle" or r.mode == "Navigation" or r.mode == "Station" or r.mode == "Voyage" or r.mode == "NO_BAG_RECORD")
  |> group(columns: ["mode"])
  |> sum()
  |> keep(columns: ["mode", "_value"])
  |> group()
```

### Battery Consumption Rate per Mode (Bar Chart)
Reads pre-computed values from `battery_rates` measurement (computed by Pass 1b).
See `concepts/bar-charts.md` for detailed explanation.
```flux
from(bucket: "vessel-data")
  |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "battery_rates")
  |> filter(fn: (r) => r._field == "rate_pct_per_hour")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> keep(columns: ["mode", "_value"])
  |> group()
  |> rename(columns: {_value: "Rate (%/hour)"})
```

### Total Battery Drop per Mode (Bar Chart)
Same pre-computed measurement, different field.
```flux
from(bucket: "vessel-data")
  |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "battery_rates")
  |> filter(fn: (r) => r._field == "total_drop_pct")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> keep(columns: ["mode", "_value"])
  |> group()
  |> rename(columns: {_value: "Battery Drop (%)"})
```

### Mode Timeline with Battery Level (Combined Time Series)
Uses `battery_state.percentage`, `v.windowPeriod` + `fn: last` for adaptive resolution.
See `concepts/mode-timeline-panel.md` for detailed explanation.

### Any Sensor Filtered by Mode (example: temperature during Navigation)
```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "temperature")
  |> filter(fn: (r) => r._field == "temperature_c")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> filter(fn: (r) => r.mode == "Navigation")
```
