# Data Pipeline Flow

## Two Pipelines

There are two ways to get data into InfluxDB:

### Pipeline 1: ROS Bag → extract-bag.py → InfluxDB (Primary)
```
ROS2 .db3 bags          Python (extract-bag.py)          InfluxDB                 Grafana
──────────────          ───────────────────────          ────────                 ───────
raw sensor data  ────►  Pass 1: build mode timeline  ──►  15 measurements   ────►  query & visualize
(from mission)          Pass 2: extract all topics       8M+ points               dashboards, charts
                        tag every point with mode        mode on every point      template variables
```

This is the primary pipeline. It reads ROS2 bag files directly, preserving original timestamps and all sensor data. Every data point gets tagged with the active mode at that timestamp.

### Pipeline 2: CSV → write.js → InfluxDB (Legacy)
```
CSV File                 Node.js (write.js)               InfluxDB                 Grafana
────────                 ──────────────────               ────────                 ───────
summary data   ──────►  parse CSV rows          ──────►  store as points   ──────►  query & visualize
(from Excel)            tag with mission name             in bucket                pie charts, bar charts
                        write to InfluxDB
```

The original pipeline. Useful for pre-computed summary data (e.g. from Excel reports). Limited because Excel loses original timestamps and only provides aggregated values.

## Pipeline 1: ROS Bag Extraction (Detailed)

### 1. Data Source: ROS2 .db3 Bag Files

Raw sensor recordings from the vessel's ROS2 system, split into ~120-second segments:
```
/home/alam/post-mission-analysis/rosbags/
├── 20260223_050019_0.db3      (first segment)
├── 20260223_050019_1.db3
├── ...
└── 20260223_174208_339.db3    (last segment)
```
Total: 722 files, ~68 GB, 14.7 hours of mission data.

### 2. Data Ingestion: extract-bag.py

**Pass 1 — Mode Timeline** (sequential, reads all files):
- Scans `/control_mode/feedback` topic across all bags
- Builds ordered list of mode segments (mode, start_time, end_time, duration_s)
- Writes `mission_segments` measurement to InfluxDB

**Pass 2 — Sensor Extraction** (parallel, 8 workers):
- Processes 14 other topics (battery, odometry, GNSS, IMU, etc.)
- Each point gets mode tag via binary search on mode timeline
- Batch writes to InfluxDB (5000 points per batch)

Usage:
```bash
# Single file
python3 extract-bag.py --mission rosbag-20260223 --bag /path/to/file.db3

# Full directory, parallel
python3 extract-bag.py --mission rosbag-20260223 --bag-dir /path/to/rosbags/ --workers 8
```

### 3. Data Storage: InfluxDB

Data is stored in the `vessel-data` bucket under 15 measurements:

```
Bucket: vessel-data
│
├── mission_segments     ← mode timeline (305 segments)
├── battery_telemetry    ← charge %, voltage, is_charging
├── battery_state        ← voltage, current, temperature
├── odometry             ← position, orientation, velocity
├── ekf_euler            ← roll, pitch, yaw, status flags
├── telemetry_state      ← lat, lon, heading, speed, depth
├── power_mgmt           ← load current, bus voltage, temp
├── gnss                 ← latitude, longitude, altitude
├── navheading           ← orientation quaternion
├── temperature          ← temperature_c
├── humidity             ← relative_humidity
├── pressure             ← fluid_pressure
├── pack_status          ← SOC, voltage, current, health
├── leak_detect          ← status
└── vessel_mode          ← staging/active
```

Every point tagged with: `mission`, `vessel`, `mode`

### 4. Data Visualization: Grafana

Provisioned dashboard at `provisioning/dashboards/mission-overview/mode-distribution.json` with 4 panels:

1. **Battery consumption rate** (bar chart) — %/hour drain per mode
2. **Total battery drop %** (bar chart) — total discharge per mode
3. **Mode distribution** (pie chart) — time spent in each mode
4. **Mode transitions with battery level** (time series) — colored mode backgrounds with battery % line overlay
5. **Temperature over time** (time series) — colored mode backgrounds with temperature line overlay

## Pipeline 2: CSV Ingestion (Detailed)

### 1. Data Source: CSV File

CSV from post-mission analysis (via Excel export):

```csv
Segment #,Mode,Start (ns),End (ns),Duration (s),Start Time,End Time
1,Direct,1.77163E+18,1.77165E+18,19041.95278,2026-02-21 05:00:39,2026-02-21 10:18:01
```

### 2. Data Ingestion: write.js

```
CSV Row                          InfluxDB Point
───────                          ──────────────
Segment # = 1            →       intField("segment_number", 1)
Mode = "Direct"          →       tag("mode", "Direct")
Duration (s) = 19041.95  →       floatField("duration_s", 19041.95)
Start Time               →       timestamp (converted to milliseconds)
CLI arg: --mission        →       tag("mission", "mission-001")
Default tag               →       tag("vessel", "AUV_01")
```

The mapping is driven by `data-types.json` — write.js reads the config to know which CSV
columns become tags, fields, and the timestamp. No code changes needed for new data types.

Usage:
```bash
node write.js --mission mission-001 --type mission-segments --csv ./pm-data/mode-segments.csv
```

## Adding a New Mission

### From ROS bags (preferred):
```bash
python3 extract-bag.py --mission mission-002 --bag-dir /path/to/new-bags/ --workers 8
# Open Grafana → Mission dropdown now shows "mission-002"
```

### From CSV (legacy):
```bash
node write.js --mission mission-002 --type mission-segments --csv /path/to/new-data.csv
```

No code changes. No dashboard changes. No provisioning changes.

## What Lives Where

```
Your machine (host)
├── ./extract-bag.py                    ← ROS bag → InfluxDB (primary pipeline)
├── ./write.js                          ← CSV → InfluxDB (legacy pipeline)
├── ./data-types.json                   ← CSV column mappings for write.js
├── ./pm-data/                          ← CSV files (legacy)
├── ./panel-templates/                  ← reusable Grafana panel JSON templates
│   ├── mode-timeline-with-overlay.json
│   ├── bar-chart-battery-drop.json
│   ├── bar-chart-consumption-rate.json
│   ├── state-timeline.json
│   └── time-series-line.json
├── ./concepts/                         ← documentation
├── ./volumes/influxdb-data/            ← InfluxDB stores data here
├── ./volumes/grafana-data/             ← Grafana state (sessions, etc.)
├── ./provisioning/                     ← auto-loaded by Grafana on startup
│   ├── datasources/influxdb.yml
│   └── dashboards/
│       ├── provider.yml
│       └── mission-overview/mode-distribution.json
│
├── Docker container: influxdb
│   ├── /var/lib/influxdb2  ←──── bind mount ────→  ./volumes/influxdb-data/
│   └── /etc/influxdb2      ←──── bind mount ────→  ./volumes/influxdb-config/
│
└── Docker container: grafana
    ├── /var/lib/grafana                    ←── bind mount ──→  ./volumes/grafana-data/
    ├── /etc/grafana/provisioning/datasources ←── bind mount ──→  ./provisioning/datasources/
    └── /etc/grafana/provisioning/dashboards  ←── bind mount ──→  ./provisioning/dashboards/
```

## Network Topology

```
Your Browser
    │
    ├── http://localhost:8086  ──────►  InfluxDB container (port 8086)
    │                                       ▲
    │                                       │ http://influxdb:8086
    │                                       │ (internal docker network)
    │                                       │
    └── http://localhost:3000  ──────►  Grafana container (port 3000)

Both containers share the "influx-net" bridge network.
Grafana uses "http://influxdb:8086" (container name) to talk to InfluxDB.
Your browser uses "http://localhost:PORT" to access either service.
```
