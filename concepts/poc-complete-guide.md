# POC: ROS Bag Data to Grafana Dashboard — Complete Guide

This document explains the **complete pipeline** from raw ROS bag files to interactive Grafana dashboards. It covers every step: infrastructure, data extraction, storage, querying, and visualization.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Infrastructure Setup](#2-infrastructure-setup)
3. [Data Source: ROS Bag Files](#3-data-source-ros-bag-files)
4. [Extraction Pipeline (extract-bag.py)](#4-extraction-pipeline-extract-bagpy)
5. [Data Storage in InfluxDB](#5-data-storage-in-influxdb)
6. [Grafana Configuration](#6-grafana-configuration)
7. [Dashboard Panels — Detailed Breakdown](#7-dashboard-panels--detailed-breakdown)
8. [Query Language: Flux](#8-query-language-flux)
9. [How to Reproduce from Scratch](#9-how-to-reproduce-from-scratch)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Architecture Overview

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   ROS Bag Files  │     │     InfluxDB      │     │     Grafana      │
│   (.db3 files)   │────>│  (Time-Series DB) │────>│   (Dashboard)    │
│   722 files      │     │   vessel-data     │     │   8 Panels       │
│   68 GB          │     │   17 measurements │     │   Port 3000      │
│                  │     │   Port 8086       │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
        │                         ▲                        ▲
        │                         │                        │
        └─── extract-bag.py ──────┘                        │
             (Python script)                               │
                                                           │
                                    Flux queries ──────────┘
                                    (InfluxDB query language)
```

**The flow:**

1. **ROS bag files** — binary recordings from an AUV (Autonomous Underwater Vehicle) containing sensor data from multiple topics (battery, temperature, heading, GPS, etc.)
2. **extract-bag.py** — Python script that reads .db3 files, deserializes ROS2 messages, and writes structured data to InfluxDB
3. **InfluxDB** — time-series database optimized for timestamped data. Stores 9.85 million data points across 17 measurements
4. **Grafana** — web-based visualization tool that queries InfluxDB using Flux and renders interactive charts

**All three services (InfluxDB, Grafana, and the extraction script) run on a single machine.** InfluxDB and Grafana run as Docker containers. The extraction script runs directly on the host.

---

## 2. Infrastructure Setup

### 2.1 Docker Compose

**File:** `docker-compose.yml`

The entire infrastructure is defined in a single Docker Compose file:

```yaml
services:
  influxdb:
    image: influxdb:2.7
    container_name: influxdb
    restart: unless-stopped
    ports:
      - "8086:8086" # InfluxDB API + UI
    volumes:
      - ./volumes/influxdb-data:/var/lib/influxdb2 # Database files
      - ./volumes/influxdb-config:/etc/influxdb2 # Config files
    networks:
      - influx-net

  grafana:
    image: grafana/grafana:10.1.2
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000" # Grafana UI
    volumes:
      - ./volumes/grafana-data:/var/lib/grafana # Grafana state
      - ./provisioning/datasources:/etc/grafana/provisioning/datasources # Auto-configure datasource
      - ./provisioning/dashboards:/etc/grafana/provisioning/dashboards # Auto-load dashboards
      - ./grafana.ini:/etc/grafana/grafana.ini # SMTP/alerting config
    networks:
      - influx-net

networks:
  influx-net:
    driver: bridge # Private network between containers
```

**Key points:**

- Both containers share a Docker network (`influx-net`), so Grafana connects to InfluxDB at `http://influxdb:8086` (the Docker container name acts as a hostname — not `localhost`)
- Data persists in `./volumes/` directory via bind mounts — stopping/restarting containers does NOT lose data
- `restart: unless-stopped` means containers auto-start on machine reboot
- Grafana version is pinned at `10.1.2` for reproducibility

### 2.2 Datasource Configuration

Grafana needs to know how to connect to InfluxDB. This is auto-configured via provisioning — no manual UI setup needed.

**File:** `provisioning/datasources/influxdb.yml`

```yaml
apiVersion: 1

datasources:
  - name: InfluxDB
    type: influxdb
    access: proxy
    uid: edd9ef0c-7cef-4d36-a9a5-ee779e3353e1 # Unique ID referenced by all dashboard panels
    url: http://influxdb:8086 # Docker internal hostname (NOT localhost)
    jsonData:
      version: Flux # Query language (InfluxDB 2.x uses Flux)
      organization: Rekise Marine # InfluxDB org name
      defaultBucket: vessel-data # Default bucket for queries
    secureJsonData:
      token: XZvi_7cfAtdoSsmdG_-1enydzbGSlTYSqmEgB2XAuwxRqpzXbeP_ThABKMyLPfCmOr1rueEXQde_wthNJwz1tw==
```

**How this works:** When Grafana starts, it reads this file and automatically creates the InfluxDB datasource. The `uid` is important — every panel in the dashboard JSON references this UID to know which datasource to query.

### 2.3 Dashboard Provider Configuration

Tells Grafana to auto-load dashboard JSON files from disk.

**File:** `provisioning/dashboards/provider.yml`

```yaml
apiVersion: 1

providers:
  - name: default
    orgId: 1
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10 # Checks for file changes every 10 seconds
    allowUiUpdates: true # Allows editing in UI too (saved to DB, not back to file)
    options:
      path: /etc/grafana/provisioning/dashboards
      foldersFromFilesStructure: true # Subdirectory names become Grafana folders
```

**How it works:** Any `.json` file placed under `provisioning/dashboards/` is automatically loaded as a Grafana dashboard. Edit the JSON file on disk → wait 10 seconds → refresh browser → changes appear. The subdirectory `mission-overview/` becomes a Grafana folder named "mission-overview" in the UI.

### 2.4 Directory Structure

```
influxWithGraphana/
├── extract-bag.py                    # Main pipeline: ROS bag → InfluxDB (Python)
├── docker-compose.yml                # InfluxDB + Grafana container definitions
├── grafana.ini                       # Grafana server config (SMTP for email alerts)
│
├── provisioning/                     # Grafana auto-configuration files
│   ├── datasources/
│   │   └── influxdb.yml              # InfluxDB connection config (token, org, bucket)
│   └── dashboards/
│       ├── provider.yml              # Dashboard file watcher config (10s interval)
│       └── mission-overview/         # Folder name → becomes Grafana folder in UI
│           └── mode-distribution.json # Main dashboard: 8 panels (all Flux queries inside)
│
├── panel-templates/                   # Reusable panel JSON snippets (copy into dashboards)
│   ├── mode-timeline-with-overlay.json
│   ├── bar-chart-battery-drop.json
│   ├── bar-chart-consumption-rate.json
│   ├── temperature-over-time.json
│   ├── state-timeline.json
│   └── time-series-line.json
│
├── volumes/                           # Persistent data (Docker bind mounts, NOT in git)
│   ├── influxdb-data/                 # InfluxDB database files (TSM engine)
│   ├── influxdb-config/               # InfluxDB server configuration
│   └── grafana-data/                  # Grafana plugins, sessions, sqlite DB
│
├── tracking/                          # Extraction progress tracking
│   └── rosbag-20260223-v2.json        # Tracks which .db3 files were already processed
│
└── concepts/                          # Documentation (including this file)
    ├── poc-complete-guide.md          # ← This document
    ├── bar-charts.md
    ├── rosbag-to-influxdb-extraction.md
    └── ... (15 concept docs total)
```

---

## 3. Data Source: ROS Bag Files

### 3.1 What are ROS Bag Files?

ROS (Robot Operating System) is a framework used in robotics. During operation, sensors on the robot publish data to named channels called **"topics"**. A bag recorder captures all this data into `.db3` files (SQLite format internally) with nanosecond-precision timestamps.

Think of it like a black box recorder on an airplane — it records everything the robot does.

**Our dataset:**

- **722 .db3 files** totaling **68 GB**
- Recorded during a ~24-hour AUV (Autonomous Underwater Vehicle) mission
- Split into **3 recording sessions**: 9.5 hours + 3.2 hours + 11.3 hours (recorder was stopped and restarted between sessions)
- Contains data from **16 ROS topics** covering battery, temperature, heading, GPS, leak sensors, IMU orientation, and more

### 3.2 ROS Topics in Our Data

A "topic" is a named data channel. Each topic publishes messages of a specific type at a specific rate. The message type defines the structure (what fields it has).

| ROS Topic                        | Message Type                                    | Approx. Rate   | What It Contains                                            |
| -------------------------------- | ----------------------------------------------- | -------------- | ----------------------------------------------------------- |
| `/battery_state`                 | sensor_msgs/BatteryState                        | ~0.57 Hz       | voltage, current, charge, percentage, temperature           |
| `/temperature`                   | sensor_msgs/Temperature                         | ~0.004 Hz      | Internal enclosure temperature (°C)                         |
| `/humidity`                      | sensor_msgs/RelativeHumidity                    | ~0.004 Hz      | Internal enclosure humidity (%)                             |
| `/pressure`                      | sensor_msgs/FluidPressure                       | ~0.004 Hz      | Pressure reading                                            |
| `/odometry/filtered`             | nav_msgs/Odometry                               | ~20 Hz         | Position (x,y,z), orientation quaternion, velocity          |
| `/moving_base_second/navheading` | sensor_msgs/Imu                                 | ~5 Hz          | GPS-based heading (quaternion format)                       |
| `/gnss/fix`                      | sensor_msgs/NavSatFix                           | ~5 Hz          | GPS latitude/longitude/altitude                             |
| `/vessel/mode`                   | rkse_common_interfaces/VesselMode               | rare           | Staging (0) or Active (1) — only 1 message                  |
| `/telemetry/state`               | rkse_telemetry_interfaces/StateTelemetry        | ~1 Hz          | lat, lon, heading, depth, altitude, speed, yaw_rate         |
| `/telemetry/battery_state`       | rkse_telemetry_interfaces/BatteryStateTelemetry | ~1 Hz          | voltage, charge %, is_charging, error_code                  |
| `/pack_status`                   | rkse_orion_interfaces/PackStatus                | ~0.5 Hz        | BMS data: state of charge, voltage, current, health, cycles |
| `/pm/feedback`                   | rkse_driver_interfaces/PowerManagementFeedback  | ~0.05 Hz       | Power card: load_current, bus_voltage, temperature          |
| `/leak_detect`                   | rkse_common_interfaces/LeakStatus               | ~0.002 Hz      | Leak sensor (0=no leak, 1=sensor A, 2=sensor B, 3=both)     |
| `/imu/ellipse/sbg_ekf_euler`     | sbg_driver/SbgEkfEuler                          | ~25 Hz         | Roll, pitch, yaw from SBG Ellipse IMU                       |
| `/imu/ahrs8/data`                | sensor_msgs/Imu                                 | ~20 Hz         | Orientation quaternion from AHRS8 IMU                       |
| `/control_mode/feedback`         | rkse_common_interfaces/ControlModeFeedback      | on change only | Current operational mode name (only ~411 messages total)    |

**Note on message types:** Topics starting with `rkse_` or `sbg_driver/` use **custom message types** specific to this AUV. The standard `rosbags` Python library doesn't know about them — they must be manually registered before deserialization (see Section 4.5).

### 3.3 Operational Modes

The AUV operates in 5 modes:

- **Direct** — manual joystick control by a human operator
- **Idle** — no active task, vehicle is stationary
- **Navigation** — autonomous waypoint following
- **Station** — station-keeping (actively holding position against currents)
- **Voyage** — long-distance autonomous travel

The `/control_mode/feedback` topic publishes a message **only when the mode changes** (not continuously). Across 722 bag files, there are only ~411 feedback messages. Each message contains a `current_mode_name` string field telling us what mode the AUV just switched to.

**Important:** There is also a `/control_mode/status` topic, but it always reports "Idle" regardless of actual mode — it is NOT reliable. Only `/control_mode/feedback` has correct mode data.

---

## 4. Extraction Pipeline (extract-bag.py)

**File:** `extract-bag.py` (root of the repository)

### 4.1 Overview

`extract-bag.py` is a ~1200-line Python script that reads ROS bag files and writes the data to InfluxDB. It uses two Python libraries:

- **`rosbags`** (v0.11.0) — pure Python library for reading ROS2 .db3 files (no ROS2 installation needed)
- **`influxdb-client`** — official Python client for writing to InfluxDB 2.x

The script runs in **three passes:**

```
Pass 1:   Build mode timeline       (parallel scan of 722 bags → ~60s)
Pass 1b:  Compute battery rates     (parallel scan for battery data → ~60s)
Pass 2:   Extract all sensor data   (16 parallel workers → ~130s)
                                    ──────────────────────────────────
                                    Total: ~3.3 minutes for 68 GB / 9.85M points
```

### 4.2 Python Dependencies

```bash
pip3 install influxdb-client rosbags
```

- `influxdb-client` — connects to InfluxDB, creates Points, batch writes
- `rosbags` — reads .db3 bag files, deserializes CDR-encoded messages

### 4.3 InfluxDB Connection Config

Defined at the top of `extract-bag.py` (lines 22-26):

```python
# File: extract-bag.py (lines 22-26)

INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "XZvi_7cfAtdoSsmdG_-1enydzbGSlTYSqmEgB2XAuwxRqpzXbeP_ThABKMyLPfCmOr1rueEXQde_wthNJwz1tw=="
INFLUX_ORG = "Rekise Marine"
INFLUX_BUCKET = "vessel-data"
BATCH_SIZE = 5000
```

**Note:** The extraction script connects to InfluxDB at `localhost:8086` (directly from host). Grafana connects at `influxdb:8086` (Docker internal network). Both reach the same InfluxDB instance.

### 4.4 Pass 1: Build Mode Timeline

**Problem:** The `/control_mode/feedback` topic only publishes when the mode changes (~411 messages across 722 files). To tag every sensor reading with the correct mode, we need a complete timeline: "from time A to time B, the mode was X".

**Algorithm (7 steps, matching the reference `mission_time_analysis` implementation):**

**Step 1 — Parallel bag scan** (function: `collect_bag_intervals_and_mode_events()`, line 220):

```python
# File: extract-bag.py — _scan_single_bag() worker (lines 187-217)

def _scan_single_bag(bag_path):
    """Worker function: scan one bag for time bounds and feedback events."""
    worker_typestore = get_typestore(Stores.ROS2_HUMBLE)
    # ... register custom types ...

    with Reader(bag_path) as reader:
        bag_info = {
            "start_time": reader.start_time,   # First message timestamp (ns)
            "end_time": reader.end_time,       # Last message timestamp (ns)
        }
        events = []
        if "/control_mode/feedback" in reader.topics:
            for connection, timestamp, rawdata in reader.messages():
                if connection.topic == "/control_mode/feedback":
                    msg = worker_typestore.deserialize_cdr(rawdata, connection.msgtype)
                    mode_name = msg.current_mode_name   # e.g., "Navigation"
                    events.append((timestamp, mode_name))
        return bag_info, events
```

Runs 16 parallel workers using Python's `multiprocessing.Pool`. Each worker opens one bag, reads its time bounds and any feedback messages. Result: 722 bag intervals + 411 mode events.

**Step 2 — Compute recording sessions** (function: `compute_recording_sessions()`, line 249):
Bags within 2 seconds of each other are merged into the same session. Gaps larger than 2 seconds mean the recorder was stopped and restarted. Result: 3 sessions (9.5h + 3.2h + 11.3h).

**Step 3 — Build raw segments** (function: `build_raw_segments()`, line 282):
A new segment starts every time the mode changes. Result: 305 raw segments.

**Step 4 — Extend to session boundaries** (function: `extend_segments_to_sessions()`, line 303):
Since `/control_mode/feedback` only publishes on **mode change**, the first feedback message in a session tells us what mode was already active when recording started. We extend the first segment back to the session start, and the last segment forward to the session end.

**Step 5 — Split at session boundaries** (function: `split_at_session_boundaries()`, line 357):
If a segment somehow spans two recording sessions, split it at the boundary.

**Step 6 — Insert gap segments** (function: `insert_gap_segments()`, line 388):
Fill any remaining gaps:

- `NO_DATA` — gap within a session (recorder running but no feedback)
- `NO_BAG_RECORD` — gap between sessions (recorder was stopped)

**Step 7 — Merge consecutive** (function: `merge_consecutive_segments()`, line 447):
Adjacent segments with the same mode are merged. Result: **309 final segments** covering the entire timeline.

**The ModeTimeline class** (line 163) provides O(log n) mode lookup using binary search:

```python
# File: extract-bag.py (lines 163-182)

class ModeTimeline:
    def __init__(self, segments):
        self.segments = segments
        self.start_times = [seg["start_time"] for seg in segments]
        self.end_times = [seg["end_time"] for seg in segments]

    def lookup(self, timestamp_ns):
        """Given a nanosecond timestamp, return the active mode name."""
        if not self.segments:
            return "UNKNOWN"
        idx = bisect.bisect_right(self.start_times, timestamp_ns) - 1
        if idx < 0:
            return "UNKNOWN"
        if timestamp_ns >= self.end_times[idx]:
            return "UNKNOWN"
        return self.segments[idx]["mode"]
```

This is called for **every single sensor reading** in Pass 2 (~9.85 million times). The binary search makes it fast — O(log 309) ≈ 9 comparisons per lookup.

### 4.5 Custom Message Type Registration

ROS2 bags from this AUV use custom message types that the `rosbags` library doesn't know about. These are defined at the top of `extract-bag.py` and must be registered before any deserialization.

**File:** `extract-bag.py` (lines 34-157)

There are **11 custom message types** across 4 packages:

```python
# File: extract-bag.py (lines 34-152)

custom_msg_defs = [
    # --- rkse_common_interfaces (Rekise core) ---

    ("rkse_common_interfaces/msg/KeyValue",
     "string key\n"
     "string value"),

    ("rkse_common_interfaces/msg/VesselMode",
     "uint8 VESSEL_MODE_STAGING=0\n"
     "uint8 VESSEL_MODE_ACTIVE=1\n"
     "std_msgs/Header header\n"
     "uint8 value"),

    ("rkse_common_interfaces/msg/ControlModeStatus",
     "std_msgs/Header header\n"
     "rkse_common_interfaces/KeyValue[] data"),

    ("rkse_common_interfaces/msg/ControlModeFeedback",
     "std_msgs/Header header\n"
     "string manual_preset_name\n"
     "string stationary_preset_name\n"
     "string current_mode_name\n"        # <-- This is the key field for mode tracking
     "uint8 current_mode\n"
     "builtin_interfaces/Duration duration"),

    ("rkse_common_interfaces/msg/LeakStatus",
     "std_msgs/Header header\n"
     "uint8 data"),                       # 0=no leak, 1=sensor A, 2=sensor B, 3=both

    # --- rkse_telemetry_interfaces (Rekise telemetry) ---

    ("rkse_telemetry_interfaces/msg/BatteryStateTelemetry",
     "uint8 NO_ERROR=0\n"
     "uint8 LOW_BATTERY=1\n"
     "uint8 ERROR=2\n"
     "builtin_interfaces/Time stamp\n"
     "float32 voltage\n"
     "float32 charge_percentage\n"       # 0.0 to 1.0
     "bool is_charging\n"
     "uint8 error_code\n"
     "string message"),

    ("rkse_telemetry_interfaces/msg/StateTelemetry",
     "builtin_interfaces/Time stamp\n"
     "float64 latitude\n"
     "float64 longitude\n"
     "float32 heading\n"
     "float32 vertical_speed\n"
     "float32 depth\n"
     "float32 altitude\n"
     "float32 course_over_ground\n"
     "float32 speed_over_ground\n"
     "float32 yaw_rate"),

    # --- rkse_orion_interfaces (Orion BMS) ---

    ("rkse_orion_interfaces/msg/PackStatus",
     "builtin_interfaces/Time stamp\n"
     "bool charge_power_status\n"
     "bool ready_power_status\n"
     "bool multipurpose_input\n"
     "bool bms_errors_present\n"
     "bool charger_safety\n"
     "bool charge_enable\n"
     "bool discharge_enable\n"
     "float32 pack_state_of_charge\n"    # 0-100%
     "float32 pack_charge_current_limit\n"
     "float32 pack_discharge_current_limit\n"
     "float32 pack_current\n"
     "float32 pack_voltage\n"
     "float32 pack_amphours\n"
     "float32 pack_depth_of_discharge\n"
     "float32 pack_health\n"
     "float32 pack_summed_voltage\n"
     "float32 total_pack_cycles"),

    # --- rkse_driver_interfaces (power management) ---

    ("rkse_driver_interfaces/msg/PowerManagementFeedback",
     "std_msgs/Header header\n"
     "bool load_on_off\n"
     "bool adc_on_off\n"
     "bool card_limit_tripped\n"
     "float32 load_current\n"
     "float32 bus_voltage\n"
     "float32 temperature\n"
     "float32 control_current\n"
     "float32 averaged_time\n"
     "float32 value_tripped\n"
     "float32 startup_current\n"
     "bool switch_on_off\n"
     "bool watchdog_status\n"
     "bool reboot\n"
     "bool power_mode_on_off\n"
     "bool power_mode_status\n"
     "bool curr_max\n"
     "bool curr_max_warn\n"
     "bool volt_max\n"
     "bool volt_max_warn\n"
     "bool volt_min_warn\n"
     "bool volt_min\n"
     "bool temp_card_max\n"
     "bool temp_card_max_warn"),

    # --- sbg_driver (SBG Ellipse IMU) ---

    ("sbg_driver/msg/SbgEkfStatus",
     "uint8 solution_mode\n"
     "bool attitude_valid\n"
     "bool heading_valid\n"
     "bool velocity_valid\n"
     "bool position_valid\n"
     "bool vert_ref_used\n"
     "bool mag_ref_used\n"
     "bool gps1_vel_used\n"
     "bool gps1_pos_used\n"
     "bool gps1_course_used\n"
     "bool gps1_hdt_used\n"
     "bool gps2_vel_used\n"
     "bool gps2_pos_used\n"
     "bool gps2_course_used\n"
     "bool gps2_hdt_used\n"
     "bool odo_used"),

    ("sbg_driver/msg/SbgEkfEuler",
     "std_msgs/Header header\n"
     "uint32 time_stamp\n"
     "geometry_msgs/Vector3 angle\n"     # angle.x=roll, .y=pitch, .z=yaw (radians)
     "geometry_msgs/Vector3 accuracy\n"
     "sbg_driver/SbgEkfStatus status"),
]

# Registration (lines 154-157):
all_types = {}
for msgtype, msgdef in custom_msg_defs:
    all_types.update(get_types_from_msg(msgdef, msgtype))
typestore.register(all_types)
```

**Why this is needed:** When the `rosbags` library reads a bag file, the raw data is in CDR (Common Data Representation) binary format. To deserialize it into a Python object with named fields, the library needs the message definition. Standard ROS2 types (like `sensor_msgs/BatteryState`) are built-in, but custom types must be provided manually.

### 4.6 Pass 1b: Pre-Compute Battery Rates per Mode

**File:** `extract-bag.py` — functions `_scan_battery()` (line 913) and `compute_battery_rates()` (line 934)

**Problem:** We need to show "battery consumption rate per mode" in Grafana. Computing this in Flux (InfluxDB's query language) gives slightly wrong results because Flux groups by the mode tag on each point, then pairs consecutive readings. But it cannot check whether both readings in a pair are actually in the same mode segment (a brief mode switch could happen between two readings tagged with the same mode).

**Solution:** Compute the rates in Python during extraction using the exact same algorithm as the reference implementation (`mission_time_analysis`):

```python
# File: extract-bag.py — compute_battery_rates() (lines 960-1002)

# Step 1: Scan all bags in parallel for battery_state readings
# (uses _scan_battery worker, 16 parallel processes)
# Result: 49,249 battery readings sorted chronologically

# Step 2: Iterate chronologically and check mode at BOTH timestamps
for i in range(len(battery_readings) - 1):
    prev_ts, prev_pct = battery_readings[i]
    curr_ts, curr_pct = battery_readings[i + 1]

    dt_s = (curr_ts - prev_ts) / 1e9
    if dt_s <= 0:
        continue

    # Look up mode at BOTH timestamps using the mode timeline
    mode_start = mode_timeline.lookup(prev_ts)
    mode_end   = mode_timeline.lookup(curr_ts)

    # Only count if BOTH readings are in the SAME real mode
    if mode_start != mode_end:
        continue
    if mode_start in ("UNKNOWN", "NO_BAG_RECORD", "NO_DATA"):
        continue

    mode = mode_start
    delta_pct = prev_pct - curr_pct  # positive = discharging

    mode_stats[mode]["total_drop"] += delta_pct
    mode_stats[mode]["total_seconds"] += dt_s
    mode_stats[mode]["pairs"] += 1

# Step 3: Compute rate = total_drop / total_hours for each mode
# Step 4: Write to InfluxDB as 'battery_rates' measurement (1 point per mode)
```

**Written to InfluxDB as:** `battery_rates` measurement (5 points, one per mode) with fields:

- `rate_pct_per_hour` — consumption rate (%/hr)
- `total_drop_pct` — total battery drop in that mode (%)
- `total_hours` — total time in that mode (hours, from battery reading pairs)
- `total_seconds` — same in seconds
- `pairs` — number of consecutive reading pairs used

### 4.7 Topic Processor Functions

**File:** `extract-bag.py` (lines 540-770)

Each ROS topic has a dedicated processor function that extracts fields from the deserialized message. The function receives the raw message object and returns `(fields_dict, extra_tags_dict)`.

**All 15 processor functions:**

```python
# File: extract-bag.py (lines 542-554)
def process_battery_state(msg):
    """Topic: /battery_state — standard ROS BatteryState"""
    fields = {
        "voltage": float(msg.voltage),
        "current": float(msg.current),
        "charge": float(msg.charge),
        "capacity": float(msg.capacity),
        "percentage": float(msg.percentage),        # 0.0 to 1.0
        "temperature": float(msg.temperature),
        "power_supply_status": int(msg.power_supply_status),
        "power_supply_health": int(msg.power_supply_health),
        "present": bool(msg.present),
    }
    return fields, {}

# File: extract-bag.py (line 557-558)
def process_temperature(msg):
    """Topic: /temperature"""
    return {"temperature_c": float(msg.temperature)}, {}

# File: extract-bag.py (line 561-562)
def process_humidity(msg):
    """Topic: /humidity"""
    return {"relative_humidity": float(msg.relative_humidity)}, {}

# File: extract-bag.py (line 565-566)
def process_pressure(msg):
    """Topic: /pressure"""
    return {"fluid_pressure": float(msg.fluid_pressure)}, {}

# File: extract-bag.py (lines 569-585)
def process_odometry(msg):
    """Topic: /odometry/filtered — 13 fields from pose + twist"""
    fields = {
        "position_x": float(msg.pose.pose.position.x),
        "position_y": float(msg.pose.pose.position.y),
        "position_z": float(msg.pose.pose.position.z),
        "orientation_x": float(msg.pose.pose.orientation.x),
        "orientation_y": float(msg.pose.pose.orientation.y),
        "orientation_z": float(msg.pose.pose.orientation.z),
        "orientation_w": float(msg.pose.pose.orientation.w),
        "linear_velocity_x": float(msg.twist.twist.linear.x),
        "linear_velocity_y": float(msg.twist.twist.linear.y),
        "linear_velocity_z": float(msg.twist.twist.linear.z),
        "angular_velocity_x": float(msg.twist.twist.angular.x),
        "angular_velocity_y": float(msg.twist.twist.angular.y),
        "angular_velocity_z": float(msg.twist.twist.angular.z),
    }
    return fields, {}

# File: extract-bag.py (lines 588-600)
def process_navheading(msg):
    """Topic: /moving_base_second/navheading — quaternion → heading conversion"""
    x, y, z, w = float(msg.orientation.x), float(msg.orientation.y), \
                 float(msg.orientation.z), float(msg.orientation.w)
    fields = {
        "orientation_x": x, "orientation_y": y,
        "orientation_z": z, "orientation_w": w,
        "angular_velocity_x": float(msg.angular_velocity.x),
        "angular_velocity_y": float(msg.angular_velocity.y),
        "angular_velocity_z": float(msg.angular_velocity.z),
        "heading_degrees": quaternion_to_heading_degrees(x, y, z, w),  # Converted here!
    }
    return fields, {}

# File: extract-bag.py (lines 603-611)
def process_gnss(msg):
    """Topic: /gnss/fix — GPS position"""
    fields = {
        "latitude": float(msg.latitude),
        "longitude": float(msg.longitude),
        "altitude": float(msg.altitude),
        "status": int(msg.status.status),
        "service": int(msg.status.service),
    }
    return fields, {}

# File: extract-bag.py (line 614-615)
def process_vessel_mode(msg):
    """Topic: /vessel/mode — 0=STAGING, 1=ACTIVE"""
    return {"value": int(msg.value)}, {}

# File: extract-bag.py (lines 618-630)
def process_telemetry_state(msg):
    """Topic: /telemetry/state — main vessel telemetry"""
    fields = {
        "latitude": float(msg.latitude),
        "longitude": float(msg.longitude),
        "heading": float(msg.heading),
        "vertical_speed": float(msg.vertical_speed),
        "depth": float(msg.depth),
        "altitude": float(msg.altitude),
        "course_over_ground": float(msg.course_over_ground),
        "speed_over_ground": float(msg.speed_over_ground),
        "yaw_rate": float(msg.yaw_rate),
    }
    return fields, {}

# File: extract-bag.py (lines 633-640)
def process_battery_telemetry(msg):
    """Topic: /telemetry/battery_state — Rekise battery telemetry"""
    fields = {
        "voltage": float(msg.voltage),
        "charge_percentage": float(msg.charge_percentage),
        "is_charging": bool(msg.is_charging),
        "error_code": int(msg.error_code),
    }
    return fields, {}

# File: extract-bag.py (lines 643-663)
def process_pack_status(msg):
    """Topic: /pack_status — Orion BMS, 17 fields"""
    fields = {
        "charge_power_status": bool(msg.charge_power_status),
        "ready_power_status": bool(msg.ready_power_status),
        "multipurpose_input": bool(msg.multipurpose_input),
        "bms_errors_present": bool(msg.bms_errors_present),
        "charger_safety": bool(msg.charger_safety),
        "charge_enable": bool(msg.charge_enable),
        "discharge_enable": bool(msg.discharge_enable),
        "pack_state_of_charge": float(msg.pack_state_of_charge),
        "pack_charge_current_limit": float(msg.pack_charge_current_limit),
        "pack_discharge_current_limit": float(msg.pack_discharge_current_limit),
        "pack_current": float(msg.pack_current),
        "pack_voltage": float(msg.pack_voltage),
        "pack_amphours": float(msg.pack_amphours),
        "pack_depth_of_discharge": float(msg.pack_depth_of_discharge),
        "pack_health": float(msg.pack_health),
        "pack_summed_voltage": float(msg.pack_summed_voltage),
        "total_pack_cycles": float(msg.total_pack_cycles),
    }
    return fields, {}

# File: extract-bag.py (lines 666-695)
def process_power_mgmt(msg):
    """Topic: /pm/feedback — power management card, 23 fields + card_id tag"""
    fields = {
        "load_on_off": bool(msg.load_on_off),
        "adc_on_off": bool(msg.adc_on_off),
        "card_limit_tripped": bool(msg.card_limit_tripped),
        "load_current": float(msg.load_current),
        "bus_voltage": float(msg.bus_voltage),
        "temperature": float(msg.temperature),
        "control_current": float(msg.control_current),
        "averaged_time": float(msg.averaged_time),
        "value_tripped": float(msg.value_tripped),
        "startup_current": float(msg.startup_current),
        "switch_on_off": bool(msg.switch_on_off),
        "watchdog_status": bool(msg.watchdog_status),
        "reboot": bool(msg.reboot),
        "power_mode_on_off": bool(msg.power_mode_on_off),
        "power_mode_status": bool(msg.power_mode_status),
        "curr_max": bool(msg.curr_max),
        "curr_max_warn": bool(msg.curr_max_warn),
        "volt_max": bool(msg.volt_max),
        "volt_max_warn": bool(msg.volt_max_warn),
        "volt_min_warn": bool(msg.volt_min_warn),
        "volt_min": bool(msg.volt_min),
        "temp_card_max": bool(msg.temp_card_max),
        "temp_card_max_warn": bool(msg.temp_card_max_warn),
    }
    extra_tags = {}
    if hasattr(msg, 'header') and msg.header.frame_id:
        extra_tags["card_id"] = msg.header.frame_id     # e.g., "pm_altimeter(16)"
    return fields, extra_tags

# File: extract-bag.py (lines 698-710)
def process_ahrs8(msg):
    """Topic: /imu/ahrs8/data — AHRS8 IMU with quaternion → heading conversion"""
    x, y, z, w = float(msg.orientation.x), float(msg.orientation.y), \
                 float(msg.orientation.z), float(msg.orientation.w)
    fields = {
        "orientation_x": x, "orientation_y": y,
        "orientation_z": z, "orientation_w": w,
        "angular_velocity_x": float(msg.angular_velocity.x),
        "angular_velocity_y": float(msg.angular_velocity.y),
        "angular_velocity_z": float(msg.angular_velocity.z),
        "heading_degrees": quaternion_to_heading_degrees(x, y, z, w),
    }
    return fields, {}

# File: extract-bag.py (lines 713-714)
def process_leak_detect(msg):
    """Topic: /leak_detect — 0=no leak, 1=sensor A, 2=sensor B, 3=both"""
    return {"status": int(msg.data)}, {}

# File: extract-bag.py (lines 717-748)
def process_ekf_euler(msg):
    """Topic: /imu/ellipse/sbg_ekf_euler — SBG IMU with yaw → heading conversion"""
    yaw_rad = float(msg.angle.z)
    heading_deg = math.degrees(yaw_rad)
    if heading_deg < 0:
        heading_deg += 360.0
    fields = {
        "roll": float(msg.angle.x),
        "pitch": float(msg.angle.y),
        "yaw": yaw_rad,
        "heading_degrees": heading_deg,
        "accuracy_roll": float(msg.accuracy.x),
        "accuracy_pitch": float(msg.accuracy.y),
        "accuracy_yaw": float(msg.accuracy.z),
        "time_stamp": int(msg.time_stamp),
        "solution_mode": int(msg.status.solution_mode),
        "attitude_valid": bool(msg.status.attitude_valid),
        "heading_valid": bool(msg.status.heading_valid),
        "velocity_valid": bool(msg.status.velocity_valid),
        "position_valid": bool(msg.status.position_valid),
        "vert_ref_used": bool(msg.status.vert_ref_used),
        "mag_ref_used": bool(msg.status.mag_ref_used),
        "gps1_vel_used": bool(msg.status.gps1_vel_used),
        "gps1_pos_used": bool(msg.status.gps1_pos_used),
        "gps1_course_used": bool(msg.status.gps1_course_used),
        "gps1_hdt_used": bool(msg.status.gps1_hdt_used),
        "gps2_vel_used": bool(msg.status.gps2_vel_used),
        "gps2_pos_used": bool(msg.status.gps2_pos_used),
        "gps2_course_used": bool(msg.status.gps2_course_used),
        "gps2_hdt_used": bool(msg.status.gps2_hdt_used),
        "odo_used": bool(msg.status.odo_used),
    }
    return fields, {}
```

### 4.8 Topic-to-Measurement Mapping

**File:** `extract-bag.py` (lines 754-770)

This dictionary maps each ROS topic to its InfluxDB measurement name and processor function:

```python
# File: extract-bag.py (lines 754-770)

TOPIC_PROCESSORS = {
    "/battery_state":                 ("battery_state",     process_battery_state),
    "/temperature":                   ("temperature",       process_temperature),
    "/humidity":                      ("humidity",          process_humidity),
    "/pressure":                      ("pressure",          process_pressure),
    "/odometry/filtered":             ("odometry",          process_odometry),
    "/moving_base_second/navheading": ("navheading",        process_navheading),
    "/gnss/fix":                      ("gnss",              process_gnss),
    "/vessel/mode":                   ("vessel_mode",       process_vessel_mode),
    "/telemetry/state":               ("telemetry_state",   process_telemetry_state),
    "/telemetry/battery_state":       ("battery_telemetry", process_battery_telemetry),
    "/pack_status":                   ("pack_status",       process_pack_status),
    "/pm/feedback":                   ("power_mgmt",        process_power_mgmt),
    "/leak_detect":                   ("leak_detect",       process_leak_detect),
    "/imu/ellipse/sbg_ekf_euler":     ("ekf_euler",         process_ekf_euler),
    "/imu/ahrs8/data":                ("ahrs8",             process_ahrs8),
}
```

### 4.9 Quaternion to Heading Conversion

**File:** `extract-bag.py` (lines 530-536)

Two topics store heading as quaternions (x, y, z, w): `/moving_base_second/navheading` and `/imu/ahrs8/data`. This helper converts to 0-360 degrees:

```python
# File: extract-bag.py (lines 530-536)

def quaternion_to_heading_degrees(x, y, z, w):
    """Convert quaternion orientation to heading in degrees (0-360)."""
    yaw_rad = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    heading_deg = math.degrees(yaw_rad)
    if heading_deg < 0:
        heading_deg += 360.0
    return heading_deg
```

**Why convert at extraction time?** Converting in Flux would require `pivot()` to get all 4 quaternion components in one row, then a complex `atan2()` expression. It's simpler and more reliable to do it in Python.

### 4.10 Pass 2: Extract All Sensor Data

**File:** `extract-bag.py` — `process_single_bag()` (lines 803-867)

Each of the 16 parallel workers:

```python
# File: extract-bag.py — process_single_bag() (lines 803-867)

def process_single_bag(args_tuple):
    """Process one .db3 file — runs in a worker process."""
    bag_path, mission, vessel, segments_data, dry_run = args_tuple

    # Each worker gets its own typestore (can't share across processes)
    worker_typestore = get_typestore(Stores.ROS2_HUMBLE)
    # ... register custom types ...

    # Each worker gets its own mode timeline (for mode lookup)
    mode_timeline = ModeTimeline(segments_data)

    # Each worker gets its own InfluxDB connection
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    with Reader(bag_path) as reader:
        for connection, timestamp, rawdata in reader.messages():
            topic = connection.topic
            if topic not in TOPIC_PROCESSORS:
                continue

            measurement_name, processor_fn = TOPIC_PROCESSORS[topic]
            msg = worker_typestore.deserialize_cdr(rawdata, connection.msgtype)
            fields, extra_tags = processor_fn(msg)

            # Look up which mode was active at this timestamp
            mode = mode_timeline.lookup(timestamp)
            tags = {"mission": mission, "vessel": vessel, "mode": mode}

            point = create_point(measurement_name, timestamp, fields, tags, extra_tags)
            # ... batch and write every 5000 points ...
```

### 4.11 File Tracking

**File:** `extract-bag.py` (lines 873-907)

The script tracks which files have been processed per mission. Tracking data is stored in `tracking/<mission>.json`. Each file is identified by its name + size + modification time (fast fingerprinting, no content hashing).

On subsequent runs, already-processed files are skipped automatically. Use `--force` to re-process everything.

### 4.12 Running the Extraction

```bash
# Install dependencies
pip3 install influxdb-client rosbags

# Full extraction with 16 parallel workers
python3 extract-bag.py \
    --mission rosbag-20260223-v2 \
    --bag-dir /path/to/rosbags/ \
    --force \
    --workers 16

# All CLI options:
#   --mission NAME     Mission name tag (appears in Grafana dropdown)
#   --bag FILE         Single .db3 file
#   --bag-dir DIR      Directory of .db3 files
#   --vessel NAME      Vessel name tag (default: AUV_01)
#   --workers N        Parallel workers for Pass 2 (default: 1)
#   --dry-run          Process without writing to InfluxDB (for testing)
#   --force            Re-process all files (ignore tracking)
```

**Performance:** 722 files (68 GB) → 9.85M points → **3.3 minutes** with 16 workers.

**Example output:**

```
=== Setup ===
  Mission:  rosbag-20260223-v2
  Bag files: 722 new (68432 MB)
  Vessel:   AUV_01
  InfluxDB: http://localhost:8086 → vessel-data

=== Pass 1: Building mode timeline ===
  Scanning 722 bag files...
    Scanned 722/722 files...
  Found 722 bags with data, 411 feedback messages
  Recording sessions: 3
    Session 1: 286 bags, 34265s (9.5h)
    Session 2: 96 bags, 11440s (3.2h)
    Session 3: 340 bags, 40688s (11.3h)
  Raw segments: 305 → Final: 309 (after extension/gaps/merge)

=== Pass 1b: Computing battery rates per mode ===
  Found 49249 battery readings
  Battery rates per mode:
    Direct: drop=-61.00%, hours=10.90h, rate=-5.60%/hr, pairs=22378
    Idle: drop=6.00%, hours=5.73h, rate=1.05%/hr, pairs=11759
    Navigation: drop=37.00%, hours=5.77h, rate=6.42%/hr, pairs=11829
    Station: drop=0.50%, hours=1.16h, rate=0.43%/hr, pairs=2370
    Voyage: drop=3.00%, hours=0.33h, rate=9.19%/hr, pairs=669

=== Pass 2: Processing sensor topics (16 workers) ===
  [722/722] ... 9.85M points total

=== Summary ===
  Elapsed: 198.0s (3.3 min)
Done!
```

---

## 5. Data Storage in InfluxDB

### 5.1 InfluxDB Concepts

InfluxDB is a time-series database designed for timestamped data. Key concepts:

- **Bucket** — a container for data (like a database). Ours is called `vessel-data`
- **Measurement** — a logical group of related data points (like a table). E.g., `battery_state`, `temperature`
- **Tags** — indexed string key-value pairs for fast filtering. E.g., `mission="rosbag-20260223-v2"`, `mode="Navigation"`
- **Fields** — the actual data values (not indexed). E.g., `voltage=26.5`, `temperature_c=23.3`
- **Timestamp** — nanosecond-precision time for each data point

**Connection details:**

- **URL:** http://localhost:8086 (from host) / http://influxdb:8086 (from Grafana container)
- **Org:** `Rekise Marine`
- **Bucket:** `vessel-data`

### 5.2 Tags on Every Point

Every single data point written by `extract-bag.py` gets these tags:

- **mission** — e.g., `rosbag-20260223-v2` (separates data per extraction run)
- **vessel** — e.g., `AUV_01`
- **mode** — e.g., `Direct`, `Idle`, `Navigation`, `Station`, `Voyage`, `NO_BAG_RECORD`, `UNKNOWN`

**Why mode on every point?** This is a key design decision. Instead of storing mode in a separate table and doing joins at query time, we tag every sensor reading with the active mode. This means:

- Filter ANY measurement by mode: `filter(fn: (r) => r.mode == "Navigation")`
- Group ANY measurement by mode for per-mode analysis
- No expensive Flux joins — mode info is already embedded in every row

**Trade-off:** Higher storage size (mode string repeated on every point) but dramatically simpler and faster queries.

### 5.3 All 17 Measurements

| #   | Measurement         | Source ROS Topic               | Point Count | Key Fields                                             |
| --- | ------------------- | ------------------------------ | ----------- | ------------------------------------------------------ |
| 1   | `mission_segments`  | /control_mode/feedback         | 309         | duration_s, start_time_ns, end_time_ns, segment_number |
| 2   | `battery_rates`     | /battery_state (pre-computed)  | 5           | rate_pct_per_hour, total_drop_pct, total_hours, pairs  |
| 3   | `battery_state`     | /battery_state                 | 49K         | voltage, current, charge, percentage, temperature      |
| 4   | `temperature`       | /temperature                   | 238         | temperature_c                                          |
| 5   | `humidity`          | /humidity                      | 238         | relative_humidity                                      |
| 6   | `pressure`          | /pressure                      | 238         | fluid_pressure                                         |
| 7   | `odometry`          | /odometry/filtered             | 1.73M       | position x/y/z, orientation quaternion, velocity       |
| 8   | `navheading`        | /moving_base_second/navheading | 432K        | orientation quaternion, heading_degrees                |
| 9   | `gnss`              | /gnss/fix                      | 432K        | latitude, longitude, altitude, status                  |
| 10  | `vessel_mode`       | /vessel/mode                   | 1           | value (0=STAGING, 1=ACTIVE)                            |
| 11  | `telemetry_state`   | /telemetry/state               | 86K         | lat, lon, heading, depth, altitude, speed              |
| 12  | `battery_telemetry` | /telemetry/battery_state       | 86K         | voltage, charge_percentage, is_charging                |
| 13  | `pack_status`       | /pack_status                   | 43K         | soc, voltage, current, health, cycles                  |
| 14  | `power_mgmt`        | /pm/feedback                   | 3.3K        | load_current, bus_voltage, temperature                 |
| 15  | `leak_detect`       | /leak_detect                   | 119         | status (0=no leak, 1/2=sensor A/B, 3=both)             |
| 16  | `ekf_euler`         | /imu/ellipse/sbg_ekf_euler     | 2.16M       | roll, pitch, yaw, heading_degrees, 15 status flags     |
| 17  | `ahrs8`             | /imu/ahrs8/data                | 1.73M       | orientation quaternion, heading_degrees                |

**Total: ~9.85 million data points**

### 5.4 Summary vs Time-Series Measurements

Two of the 17 measurements are **summary data** (pre-computed during extraction), not raw time-series:

1. **`mission_segments`** — 309 points, one per mode segment. Each has `duration_s`, `start_time_ns`, `end_time_ns`. Used by the pie chart.
2. **`battery_rates`** — 5 points, one per operational mode. Each has `rate_pct_per_hour`, `total_drop_pct`. Used by the bar charts.

These are stored at **epoch timestamps** (not real mission timestamps), so Flux queries must use `range(start: 0)` instead of the dashboard time range to find them.

---

## 6. Grafana Configuration

### 6.1 Access

- **URL:** http://localhost:3000
- **Credentials:** admin / admin

### 6.2 Template Variables

**File:** `provisioning/dashboards/mission-overview/mode-distribution.json` — `"templating"` section

The dashboard has a **mission dropdown** that lets users select which mission's data to view:

```json
"templating": {
    "list": [{
        "name": "mission",
        "type": "query",
        "query": "import \"influxdata/influxdb/schema\"\nschema.tagValues(bucket: \"vessel-data\", tag: \"mission\")",
        "current": {"text": "rosbag-20260223-v2", "value": "rosbag-20260223-v2"}
    }]
}
```

**How it works:**

1. When the dashboard loads, this query runs against InfluxDB: "give me all distinct values of the `mission` tag"
2. The results become dropdown options (e.g., "rosbag-20260223-v2")
3. The selected value is available as `${mission}` in all panel queries
4. When the user selects a different mission, all panels automatically re-query with the new filter

### 6.3 Dashboard Layout

**File:** `provisioning/dashboards/mission-overview/mode-distribution.json`

The dashboard has **8 panels** arranged vertically:

```
┌─────────────────────────┬─────────────────────────┐
│  Battery Consumption    │                          │
│  Rate (%/hr) [bar]      │    (half width each)     │
├─────────────────────────┤                          │
│  Total Battery          │                          │
│  Drop % [bar]           │                          │
├─────────────────────────┤                          │
│  Mode Distribution      │                          │
│  [pie chart]            │                          │
├─────────────────────────┴──────────────────────────┤
│  Mode Transitions with Battery Level [timeseries]  │  ← full width
├────────────────────────────────────────────────────┤
│  Temperature Over Time [timeseries]                │  ← full width
├────────────────────────────────────────────────────┤
│  Humidity Over Time [timeseries]                   │  ← full width
├────────────────────────────────────────────────────┤
│  Heading Comparison [timeseries]                   │  ← full width
├────────────────────────────────────────────────────┤
│  Leak Detection [timeseries]                       │  ← full width
└────────────────────────────────────────────────────┘
```

### 6.4 Mode Color Scheme

All time-series panels use consistent mode colors as background bands:

| Mode       | Color         | Hex Code  |
| ---------- | ------------- | --------- |
| Direct     | Light Blue    | `#73BFF2` |
| Idle       | Gray          | `#B0B0B0` |
| Navigation | Purple        | `#8F3BB8` |
| Station    | Bright Purple | `#C840E9` |
| Voyage     | Navy          | `#3274D9` |

---

## 7. Dashboard Panels — Detailed Breakdown

All panels are defined in a single file:
**File:** `provisioning/dashboards/mission-overview/mode-distribution.json`

### 7.1 Panel: Battery Consumption Rate (panel id: 3)

**Type:** Bar Chart (`"type": "barchart"`)
**What it shows:** How fast the battery drains in each operational mode (%/hour).

**Data source:** `battery_rates` measurement (pre-computed by extract-bag.py Pass 1b)

**Flux query (refId: A):**

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

**How the query works, line by line:**

1. `from(bucket: "vessel-data")` — start reading from our data bucket
2. `range(start: 0)` — read ALL data from epoch (battery_rates are summary data, not within dashboard time range)
3. `filter _measurement == "battery_rates"` — select only the pre-computed battery rates
4. `filter _field == "rate_pct_per_hour"` — we want the rate field (not total_drop or total_hours)
5. `filter mission == "${mission}"` — filter to the mission selected in the dropdown
6. `filter mode != "UNKNOWN"...` — exclude non-operational modes
7. `keep` — drop all metadata columns, keep only `mode` (string) and `_value` (number)
8. `group()` — ungroup so all rows are in one table (needed for bar chart)
9. `rename` — rename `_value` to "Rate (%/hour)" so the chart legend shows a readable name

**Result data:**
| mode | Rate (%/hour) |
|------|---------------|
| Direct | -5.60 |
| Navigation | 6.42 |
| Voyage | 9.19 |
| Idle | 1.05 |
| Station | 0.43 |

**Visual config:**

- Color gradient: green (low values) → yellow → red (high values) via `"color.mode": "continuous-GrYlRd"`
- X-axis: mode names (`"xField": "mode"`)
- Y-axis label: "Rate (%/hour)"
- Values displayed on bars (`"showValue": "always"`)

---

### 7.2 Panel: Total Battery Drop % (panel id: 11)

**Type:** Bar Chart (`"type": "barchart"`)
**What it shows:** Total battery percentage consumed in each mode across the entire mission.

**Flux query (refId: A):**

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

Identical structure to Panel 7.1, but reads `total_drop_pct` field instead of `rate_pct_per_hour`.

**Result data:**
| mode | Battery Drop (%) |
|------|-----------------|
| Direct | -61.00 |
| Navigation | 37.00 |
| Voyage | 3.00 |
| Idle | 6.00 |
| Station | 0.50 |

---

### 7.3 Panel: Mode Distribution — Pie Chart (panel id: 1)

**Type:** Pie Chart (`"type": "piechart"`)
**What it shows:** How much time was spent in each operational mode (as proportional slices).

**Flux query (refId: A):**

```flux
from(bucket: "vessel-data")
  |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "mission_segments")
  |> filter(fn: (r) => r._field == "duration_s")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> filter(fn: (r) => r.mode == "Direct" or r.mode == "Idle"
      or r.mode == "Navigation" or r.mode == "Station"
      or r.mode == "Voyage" or r.mode == "NO_BAG_RECORD")
  |> group(columns: ["mode"])
  |> sum()
  |> keep(columns: ["mode", "_value"])
  |> group()
```

**How it works:**

1. `range(start: 0)` — mission_segments are summary data stored at segment start times, must read ALL data
2. Reads `duration_s` from `mission_segments` — each of the 309 segments has a duration in seconds
3. Filters to 5 operational modes + NO_BAG_RECORD (excludes NO_DATA, UNKNOWN)
4. `group(columns: ["mode"])` + `sum()` — groups all segments by mode and sums their durations. E.g., 82 Direct segments → one total: 39,349 seconds
5. Result: one row per mode with total time in seconds

**Result data:**
| mode | \_value (seconds) |
|------|-----------------|
| Direct | 39349 (≈ 10h 55m) |
| Idle | 20715 (≈ 5h 45m) |
| Navigation | 20838 (≈ 5h 47m) |
| Station | 4258 (≈ 1h 10m) |
| Voyage | 1233 (≈ 20m 33s) |

**Visual config:**

- Unit: `dthms` — automatically formats seconds as "10h 55m 49s"
- Color: `palette-classic` (Grafana auto-assigns colors per slice)

---

### 7.4 Panel: Mode Transitions with Battery Level (panel id: 9)

**Type:** Time Series (`"type": "timeseries"`)
**What it shows:** A timeline showing which mode was active (colored background bands) with the battery percentage overlaid as a line.

This is the most complex panel with **3 queries** working together:

**Query A (refId: A) — Mode background bands:**

```flux
data = from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "battery_state")
  |> filter(fn: (r) => r._field == "percentage")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)

union(tables: [
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Direct"     then 100.0 else 0.0, _field: "Direct"}))     |> group(columns: ["_field"]),
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Idle"        then 100.0 else 0.0, _field: "Idle"}))        |> group(columns: ["_field"]),
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Navigation"  then 100.0 else 0.0, _field: "Navigation"}))  |> group(columns: ["_field"]),
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Station"     then 100.0 else 0.0, _field: "Station"}))     |> group(columns: ["_field"]),
  data |> map(fn: (r) => ({_time: r._time, _value: if r.mode == "Voyage"      then 100.0 else 0.0, _field: "Voyage"}))      |> group(columns: ["_field"])
])
```

**How mode backgrounds work (the "stacked area trick"):**

1. Read battery_state data (chosen because it has a steady ~0.57 Hz sample rate and the mode tag on every point)
2. `aggregateWindow(every: v.windowPeriod, fn: last)` — downsample to match the dashboard resolution. `v.windowPeriod` is auto-calculated by Grafana based on zoom level (e.g., 30s when zoomed in, 5m when zoomed out)
3. For EACH mode, create a new series: value = 100 when that mode is active at that timestamp, 0 otherwise
4. `union()` combines all 5 mode series into one result
5. In Grafana, these 5 series are configured as **stacked areas**: fillOpacity 50%, lineWidth 0, step interpolation. Since only one mode is active at a time, only one series is 100 (the rest are 0), creating a single colored band at each moment.
6. Each mode series gets its assigned color via field overrides

**Query B (refId: B) — Battery percentage line:**

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

- Reads the same battery_state data but keeps the actual percentage value
- Multiplies by 100 (raw value is 0.0-1.0, we want 0-100%)
- Renames to "Battery %" for the legend
- Configured as a smooth line on the **right Y-axis** (0-100%), lineWidth 3, dark blue (`#0000CC`)

**Query C (refId: C) — Mode tooltip (invisible series):**

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "battery_state")
  |> filter(fn: (r) => r._field == "percentage")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time,
      _value: if r.mode == "Direct" then 1.0
              else if r.mode == "Idle" then 2.0
              else if r.mode == "Navigation" then 3.0
              else if r.mode == "Station" then 4.0
              else if r.mode == "Voyage" then 5.0
              else 0.0,
      _field: "Mode"}))
  |> group(columns: ["_field"])
```

- Maps each mode to a number (1-5)
- Configured with Grafana **value mappings**: 1→"Direct", 2→"Idle", 3→"Navigation", 4→"Station", 5→"Voyage"
- lineWidth 0, fillOpacity 0 — **completely invisible** on the chart
- Purpose: when hovering, the tooltip shows the mode name (because mode background series are hidden from tooltip)

**Grafana visual configuration:**

- Mode background series: stacking group "A", fillOpacity 50, lineWidth 0, step interpolation, each with its mode color. Hidden from tooltip and legend.
- Battery line: stacking "none" (not stacked), fillOpacity 0, lineWidth 3, smooth interpolation, right Y-axis with label "Battery (%)", color #0000CC.
- Mode tooltip: lineWidth 0, fillOpacity 0, hidden from legend, value mappings applied.

---

### 7.5 Panel: Temperature Over Time (panel id: 5)

**Type:** Time Series
**What it shows:** Internal enclosure temperature (°C) with mode-colored backgrounds.

**Query A (refId: A) — Mode backgrounds:** Same pattern as Panel 7.4 Query A, but reads from `temperature` measurement / `temperature_c` field.

**Query B (refId: B) — Temperature line:**

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "temperature")
  |> filter(fn: (r) => r._field == "temperature_c")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _value: r._value, _field: "Temperature"}))
  |> group(columns: ["_field"])
```

**Visual config:**

- Temperature line: tomato red (`#FF6347`), smooth interpolation, lineWidth 2, right Y-axis with label "Temperature (°C)", unit: celsius
- Auto-scaled Y-axis (no hardcoded min/max — adjusts to actual data range)

---

### 7.6 Panel: Humidity Over Time (panel id: 6)

**Type:** Time Series
**What it shows:** Internal enclosure humidity (%) with mode-colored backgrounds.

Same structure as Temperature panel. Reads from `humidity` measurement / `relative_humidity` field.

**Query B (refId: B) — Humidity line:**

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "humidity")
  |> filter(fn: (r) => r._field == "relative_humidity")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _value: r._value, _field: "Humidity"}))
  |> group(columns: ["_field"])
```

**Visual config:**

- Humidity line: royal blue (`#4169E1`), smooth interpolation, lineWidth 2, right Y-axis with label "Humidity (%)", unit: percent

---

### 7.7 Panel: Heading Comparison (panel id: 7)

**Type:** Time Series
**What it shows:** Heading (0-360°) from two different IMU sensors overlaid on mode backgrounds, so engineers can compare sensor accuracy.

**Query A (refId: A) — Mode backgrounds:** Same stacked area pattern, using `ekf_euler` / `heading_degrees` as the base measurement.

**Query B (refId: B) — SBG Ellipse heading (primary IMU):**

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "ekf_euler")
  |> filter(fn: (r) => r._field == "heading_degrees")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _value: r._value, _field: "SBG Ellipse"}))
  |> group(columns: ["_field"])
```

**Query C (refId: C) — AHRS8 heading (secondary IMU):**

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "ahrs8")
  |> filter(fn: (r) => r._field == "heading_degrees")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _value: r._value, _field: "AHRS8"}))
  |> group(columns: ["_field"])
```

**Visual config:**

- SBG Ellipse: tomato red (`#FF6347`), right Y-axis with label "Heading (degrees)", min: 0, max: 360, unit: degree
- AHRS8: royal blue (`#4169E1`), hidden axis (shares the 0-360° range with SBG), unit: degree

**Why `fn: last` (not `fn: mean`):** Heading data wraps around at 0°/360°. If you average values near the boundary (e.g., 1° and 359°), you get 180° — completely wrong. Using `fn: last` picks the most recent reading in each window, avoiding this problem.

**Why `heading_degrees` is pre-computed:** The raw ROS data stores heading as quaternions (x, y, z, w) or radians. Converting in Flux would require `pivot()` to get all 4 quaternion components in one row, then a complex `atan2()` expression. `extract-bag.py` converts at extraction time (see Section 4.9).

---

### 7.8 Panel: Leak Detection (panel id: 8)

**Type:** Time Series
**What it shows:** Leak sensor status over time with mode backgrounds. Green dots = no leak, red dots = leak detected.

**Query A (refId: A) — Mode backgrounds:** Same stacked area pattern, using `leak_detect` / `status` as the base measurement.

**Query B (refId: B) — No Leak (status = 0):**

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
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

**Query C (refId: C) — Leak Detected (status > 0):**

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
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

**Why `fn: max` (not `fn: last`):** Leak events can be brief — a single alarming reading within a downsampling window. Using `fn: last` might miss a leak if the last reading in the window happened to be 0. Using `fn: max` ensures the highest value (= worst leak) in each window is preserved.

**Why two separate queries instead of one?** To color them differently. "No Leak" shows as small green dots, "Leak Detected" as large red dots. Grafana applies different visual overrides per series name.

**Visual config:**

- "No Leak": green dots (`#56A64B`), point size 5, draw style: points
- "Leak Detected": red dots (`#FF0000`), point size 10 (larger for visibility), draw style: points
- Grafana value mappings: 0→"None (0)", 1→"Sensor A - Back (1)", 2→"Sensor B - Front (2)", 3→"Both (3)"
- Y-axis: 0 to 3 (integer leak codes)

---

## 8. Query Language: Flux

### 8.1 Flux Basics

Flux is InfluxDB 2.x's functional query language. Every query is a pipeline: data flows through a chain of transformations using the `|>` (pipe-forward) operator.

```flux
from(bucket: "vessel-data")                                    // 1. Start: which bucket?
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)     // 2. Time range (from Grafana)
  |> filter(fn: (r) => r._measurement == "temperature")        // 3. Which measurement?
  |> filter(fn: (r) => r._field == "temperature_c")            // 4. Which field?
  |> filter(fn: (r) => r.mission == "${mission}")               // 5. Filter by dropdown
  |> aggregateWindow(every: v.windowPeriod, fn: last)           // 6. Downsample
```

Each `|>` passes the result of the left side as input to the right side, like Unix pipes.

### 8.2 Key Flux Functions Used in This Dashboard

| Function                       | What It Does                            | Example                                                        |
| ------------------------------ | --------------------------------------- | -------------------------------------------------------------- |
| `from(bucket:)`                | Start reading from a bucket             | `from(bucket: "vessel-data")`                                  |
| `range(start:, stop:)`         | Filter by time range                    | `range(start: 0)` = all time                                   |
| `filter(fn:)`                  | Keep rows matching a condition          | `filter(fn: (r) => r.mode == "Navigation")`                    |
| `group(columns:)`              | Group rows by column(s)                 | `group(columns: ["mode"])` — one group per mode                |
| `group()`                      | Ungroup (combine all into one table)    | Needed before bar charts                                       |
| `sum()`                        | Sum values within each group            | After `group(columns: ["mode"])` → total per mode              |
| `aggregateWindow(every:, fn:)` | Downsample to fixed intervals           | `aggregateWindow(every: v.windowPeriod, fn: last)`             |
| `map(fn:)`                     | Transform each row                      | `map(fn: (r) => ({_time: r._time, _value: r._value * 100.0}))` |
| `union(tables:)`               | Combine multiple tables into one result | Used for 5 mode background series                              |
| `rename(columns:)`             | Rename columns                          | `rename(columns: {_value: "Rate (%/hour)"})`                   |
| `keep(columns:)`               | Drop all columns except listed          | `keep(columns: ["mode", "_value"])`                            |
| `sort(columns:)`               | Sort rows                               | `sort(columns: ["_time"])`                                     |

### 8.3 Grafana-Specific Variables

These are special variables that Grafana substitutes into Flux queries before sending them to InfluxDB:

| Variable           | What It Is                                                               | Example Value                              |
| ------------------ | ------------------------------------------------------------------------ | ------------------------------------------ |
| `v.timeRangeStart` | Start of the dashboard time picker                                       | `2026-02-22T00:00:00Z`                     |
| `v.timeRangeStop`  | End of the dashboard time picker                                         | `2026-02-24T00:00:00Z`                     |
| `v.windowPeriod`   | Auto-calculated aggregation window (based on zoom level and panel width) | `30s` when zoomed in, `5m` when zoomed out |
| `${mission}`       | Value from the "Mission" dropdown                                        | `rosbag-20260223-v2`                       |

### 8.4 The Mode Background Pattern (used in 5 panels)

This is the key visual pattern used in the 5 time-series panels. Grafana doesn't have a built-in "color background by tag" feature, so we simulate it:

1. **Read sensor data** (any measurement) and downsample with `aggregateWindow`
2. **For each mode**, create a new series: value = 100 when active, 0 otherwise
3. **Union** all 5 mode series
4. **Configure in Grafana** as stacked areas with 50% opacity, 0 line width, step interpolation
5. **Overlay** the actual data line on top (separate query, different stacking group)

Since only one mode is active at any timestamp, only one series has value 100 — creating a single colored band. The stacking makes them fill the background while the actual data line draws on top.

---

## 9. How to Reproduce from Scratch

### 9.1 Prerequisites

- Linux machine with Docker and Docker Compose v2 (`docker compose`, not `docker-compose`)
- Python 3.8+ with pip
- Access to ROS2 .db3 bag files from the AUV mission

### 9.2 Step-by-Step

```bash
# 1. Clone the repository
git clone git@github.com:alam-rekise/grafana-dashboard-for-post-mission-analysis.git
cd influxWithGrafana

# 2. Start the containers
docker compose up -d

# 3. Wait ~10 seconds for InfluxDB to start, then open the UI:
#    http://localhost:8086
#    Complete the onboarding wizard:
#    - Username: admin
#    - Password: <choose a password>
#    - Organization: Rekise Marine
#    - Bucket: vessel-data
#    - SAVE THE API TOKEN that's generated — you'll need it

# 4. Update the API token in TWO places (if it differs from the default):
#    a) provisioning/datasources/influxdb.yml → secureJsonData.token
#    b) extract-bag.py → INFLUX_TOKEN constant (line 23)

# 5. Install Python dependencies
pip3 install influxdb-client rosbags

# 6. Run the extraction (adjust path to your bag files)
python3 extract-bag.py \
    --mission rosbag-20260223-v2 \
    --bag-dir /path/to/your/rosbags/ \
    --force \
    --workers 16

# 7. Open Grafana at http://localhost:3000
#    - Login: admin / admin
#    - Navigate to: Dashboards → mission-overview → Mode Distribution
#    - Select your mission from the "Mission" dropdown at the top
#    - Set the time range to cover your data
#      (for rosbag-20260223-v2: set to Feb 22 2026 – Feb 24 2026)
#    - All 8 panels should now display data
```

### 9.3 Verifying the Data

After extraction, verify data was written correctly:

```bash
# Count points per measurement
curl -s --request POST "http://localhost:8086/api/v2/query?org=Rekise%20Marine" \
  --header "Authorization: Token <YOUR_TOKEN>" \
  --header "Content-Type: application/vnd.flux" \
  --data 'from(bucket:"vessel-data")
    |> range(start:0)
    |> filter(fn:(r) => r.mission == "rosbag-20260223-v2")
    |> group(columns: ["_measurement"])
    |> count()
    |> group()'

# Check battery rates specifically
curl -s --request POST "http://localhost:8086/api/v2/query?org=Rekise%20Marine" \
  --header "Authorization: Token <YOUR_TOKEN>" \
  --header "Content-Type: application/vnd.flux" \
  --data 'from(bucket:"vessel-data")
    |> range(start:0)
    |> filter(fn:(r) => r._measurement == "battery_rates")
    |> filter(fn:(r) => r._field == "rate_pct_per_hour")
    |> keep(columns: ["mode", "_value"])'
```

### 9.4 Adding New Missions

Simply run the extraction with a different `--mission` name. The new mission appears in the Grafana dropdown automatically (because the template variable queries all distinct mission tag values):

```bash
python3 extract-bag.py \
    --mission new-mission-2026-03 \
    --bag-dir /path/to/new/rosbags/ \
    --workers 16
```

---

## 10. Troubleshooting

### Panel shows "No data"

1. **Check mission dropdown** — is the correct mission selected?
2. **Check time range** — does the dashboard time picker cover the period when data was recorded? For rosbag-20260223-v2, the data is from Feb 22-24, 2026.
3. **Check InfluxDB** — run a curl query (see Section 9.3) to confirm data exists.

### Dashboard doesn't update after editing JSON

The provisioner checks every 10 seconds. If changes still don't appear:

1. Check the `"version"` field in the JSON. If someone edited the dashboard via the Grafana UI, the DB version increments. The provisioner won't overwrite if the file version < DB version.
2. Check current DB version: `curl -s -u admin:admin http://localhost:3000/api/dashboards/uid/b13d2a0c-4ab2-4a4d-8552-3531e2bc019b | python3 -c "import sys,json; print(json.load(sys.stdin)['dashboard']['version'])"`
3. Bump the file's `"version"` field higher than the DB version.

### Extraction fails with "Can't pickle local object"

This happens if a function is defined inside another function and used with `multiprocessing.Pool`. All worker functions must be at module level in `extract-bag.py`.

---

## Appendix: Key Design Decisions

| Decision                                         | Why                                                                                                                                    |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| Mode tag on every data point                     | Enables filtering/grouping any measurement by mode without expensive joins                                                             |
| Pre-computed `battery_rates` in Python           | Flux can't replicate the chronological dual-timestamp mode check that `mission_time_analysis` uses — results differ by up to 0.02 %/hr |
| `fn: last` (not `fn: mean`) for downsampling     | `fn: mean` causes wrap-around errors on heading data (averaging 1° and 359° gives 180°)                                                |
| `fn: max` for leak detection                     | Catches brief leak events that could be missed by `fn: last` within a downsampling window                                              |
| `range(start: 0)` for summary data               | `mission_segments` and `battery_rates` are stored at epoch timestamps, not within the dashboard time range                             |
| `v.windowPeriod` for adaptive resolution         | Grafana auto-calculates the window size based on zoom level — zoomed out = larger window = fewer points = faster queries               |
| Stacked 100/0 areas for mode backgrounds         | Grafana doesn't have native "color background by tag value" — stacked areas simulate colored timeline bands                            |
| Quaternion→heading conversion at extraction time | Doing it in Flux would require pivot + atan2, which is complex and error-prone                                                         |
| Tooltip mode: `"single"` (not `"all"`)           | `"all"` mode is broken in Grafana 10.1.2 with stacked series — tooltip disappears entirely                                             |
| 11 custom message type definitions in Python     | The `rosbags` library can't deserialize Rekise/SBG custom message types without explicit registration                                  |
| 16 parallel workers for extraction               | Reduces extraction time from ~40 minutes (sequential) to ~3.3 minutes for 68 GB                                                        |
