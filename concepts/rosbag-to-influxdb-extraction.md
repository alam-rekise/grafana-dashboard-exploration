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

**Pass 1 — Build Mode Timeline:**
1. Read all `/control_mode/feedback` messages (ControlModeFeedback msg type)
2. Each message has a `current_mode_name` field — the active mode (e.g. "Idle", "Navigation", "Direct", "Station", "Voyage")
3. This topic only publishes on **mode change** (not continuously) — ~411 messages across 722 files
4. Detect mode transitions (new segment only when mode actually changes)
5. Result: list of segments with mode, start_time, end_time, duration_s
6. Write as `mission_segments` measurement to InfluxDB

**Important:** `/control_mode/status` (KeyValue[] array) was initially used but always reported "Idle".
The correct mode source is `/control_mode/feedback` with `current_mode_name`, which matches
the `mission_time_analysis` package used by Rekise for post-mission reports.

**Pass 2 — Process All Sensor Topics:**
1. Single iteration through the entire bag file (reads it once, not once per topic)
2. For each message:
   - Deserialize using typestore
   - Flatten nested fields (e.g. SbgEkfEuler.angle.x → roll)
   - Look up which mode was active at that timestamp (binary search on mode timeline)
   - Create InfluxDB Point with tags: mission, vessel, mode
3. Batch write to InfluxDB per topic (flush every 5000 points)

### Mode Lookup (Binary Search)
Every sensor reading gets tagged with the mode active at its timestamp.
Uses `bisect` for O(log n) lookup instead of O(n) linear scan.
Edge cases:
- Timestamp before first mode segment → tagged as "PRE_MISSION"
- Timestamp after last mode segment → tagged as "POST_MISSION"

### Custom Message Type Registration
ROS2 bags from Rekise use custom message types (rkse_common_interfaces, rkse_telemetry_interfaces, etc.)
that the standard typestore doesn't know about.

The rosbags library needs these registered before it can deserialize messages:
```python
from rosbags.typesys.msg import get_types_from_msg

# Define the message structure as text (same format as .msg files)
custom_msg_defs = [
    ("rkse_common_interfaces/msg/KeyValue", "string key\nstring value"),
    ("rkse_common_interfaces/msg/ControlModeFeedback",
     "std_msgs/Header header\nstring manual_preset_name\n"
     "string stationary_preset_name\nstring current_mode_name\n"
     "uint8 current_mode\nbuiltin_interfaces/Duration duration"),
    ("rkse_telemetry_interfaces/msg/BatteryStateTelemetry", "..."),
    # ... more custom types
]

# Parse and register
all_types = {}
for msgtype, msgdef in custom_msg_defs:
    all_types.update(get_types_from_msg(msgdef, msgtype))
typestore.register(all_types)
```

The .msg definitions were found in: `/home/alam/workspaces/swadheen_ws/src/`

## Data Structure in InfluxDB

### Tags (indexed, for filtering)
- **mission**: e.g. "rosbag-20260223" — separates data per bag/mission
- **vessel**: e.g. "AUV_01"
- **mode**: e.g. "Idle", "Navigation", "Direct", "Station", "Voyage" — the active mode at that timestamp (from /control_mode/feedback)

### Measurements Written (15 total)

| Measurement | Source Topic | Msg Count | Key Fields |
|---|---|---|---|
| mission_segments | /control_mode/feedback | 305 segments | duration_s, start_time_ns, end_time_ns, segment_number |
| battery_state | /battery_state | 68 | voltage, current, charge, percentage, temperature |
| temperature | /temperature | 238 | temperature_c |
| humidity | /humidity | 238 | relative_humidity |
| pressure | /pressure | 119 | fluid_pressure |
| odometry | /odometry/filtered | 2387 | position x/y/z, orientation, linear/angular velocity |
| navheading | /moving_base_second/navheading | 596 | orientation quaternion, angular velocity |
| gnss | /gnss/fix | 598 | latitude, longitude, altitude, status |
| vessel_mode | /vessel/mode | 1 | value (0=STAGING, 1=ACTIVE) |
| telemetry_state | /telemetry/state | 1195 | lat, lon, heading, depth, altitude, speed, course, yaw_rate |
| battery_telemetry | /telemetry/battery_state | 120 | voltage, charge_percentage, is_charging, error_code |
| pack_status | /pack_status | 68 | 17 fields (soc, voltage, current, health, etc.) |
| power_mgmt | /pm/feedback | 3316 | 23 fields (load_current, bus_voltage, temperature, etc.) |
| leak_detect | /leak_detect | 119 | status |
| ekf_euler | /imu/ellipse/sbg_ekf_euler | 2395 | roll, pitch, yaw, accuracy, 15 status flags |

### Why Mode as a Tag on Every Point?
This enables maximum Grafana flexibility:
- Filter ANY measurement by mode: `filter(fn: (r) => r.mode == "Navigation")`
- Group ANY measurement by mode for per-mode bar charts
- Overlay any data on top of mode timeline
- No Flux joins needed — mode info is already on each point

## Usage

```bash
# Install dependency (one time)
pip3 install influxdb-client

# Dry run — single file
python3 extract-bag.py --mission test-001 --bag /path/to/file.db3 --dry-run

# Single file extraction
python3 extract-bag.py --mission rosbag-20260223 --bag /path/to/file.db3

# Batch — entire directory of .db3 files
python3 extract-bag.py --mission rosbag-20260223 --bag-dir /path/to/rosbags/

# Parallel — 8 workers (Pass 2 only, Pass 1 always sequential)
python3 extract-bag.py --mission rosbag-20260223 --bag-dir /path/to/rosbags/ --workers 8

# Force re-process (ignore tracking, re-seed everything)
python3 extract-bag.py --mission rosbag-20260223 --bag-dir /path/to/rosbags/ --force --workers 8

# With custom vessel name
python3 extract-bag.py --mission rosbag-20260223 --bag /path/to/file.db3 --vessel AUV_02
```

## Grafana Queries for ROS Bag Data

### Mode Distribution (Pie Chart)
```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "mission_segments")
  |> filter(fn: (r) => r._field == "duration_s")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group(columns: ["mode"])
  |> sum()
  |> keep(columns: ["mode", "_value"])
  |> group()
```

### Total Battery Drop per Mode (Bar Chart)
Uses `difference()` for point-to-point changes — see `concepts/bar-charts.md` for detailed explanation.
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

### Battery Consumption Rate per Mode (Bar Chart)
Uses join of battery drop + segment duration — see `concepts/bar-charts.md` for detailed explanation.
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

### Mode Timeline with Battery Level (Combined Time Series)
Single panel with colored mode backgrounds and battery % line overlaid.
See `concepts/mode-timeline-panel.md` for detailed explanation.

**Query A — Mode backgrounds** (stacked areas, 0/100 values per mode):
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
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Navigation" then 100.0 else 0.0, _field: "Navigation"})) |> group(columns: ["_field"]),
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Station" then 100.0 else 0.0, _field: "Station"})) |> group(columns: ["_field"]),
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Voyage" then 100.0 else 0.0, _field: "Voyage"})) |> group(columns: ["_field"])
])
```

**Query B — Battery % line** (overlaid on top):
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

### Any Sensor Filtered by Mode (example: temperature during Navigation)
```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "temperature")
  |> filter(fn: (r) => r._field == "temperature_c")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> filter(fn: (r) => r.mode == "Navigation")
```
