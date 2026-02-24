# Data Pipeline Flow

## End-to-End Architecture

```
CSV File                    Node.js (write.js)              InfluxDB                 Grafana
────────                    ──────────────────              ────────                 ───────
mission data   ──────►    parse CSV rows         ──────►  store time-series  ──────►  query & visualize
(from post-mission)       tag with mission name            data in bucket            pie charts, dashboards
                          write to InfluxDB                                          template variables
```

## Detailed Flow

### 1. Data Source: CSV File

The CSV comes from post-mission analysis and contains mode segments:

```csv
Segment #,Mode,Start (ns),End (ns),Duration (s),Start Time,End Time
1,Direct,1.77163E+18,1.77165E+18,19041.95278,2026-02-21 05:00:39,2026-02-21 10:18:01
2,Idle,1.77165E+18,1.77165E+18,0.595433026,2026-02-21 10:18:01,2026-02-21 10:18:01
```

Each row = one segment of the mission where the vessel was in a specific mode.

### 2. Data Ingestion: write.js

`write.js` reads the CSV and converts each row into an InfluxDB data point:

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
# Feed mission mode segments
node write.js --mission mission-001 --type mission-segments --csv ./pm-data/mode-segments.csv

# Feed navigation data (different CSV, different measurement)
node write.js --mission mission-001 --type navigation --csv ./pm-data/nav-data.csv
```

### 3. Data Storage: InfluxDB

Data is stored in the `vessel-data` bucket under different measurements per data type:

```
Bucket: vessel-data
│
├── Measurement: mission_segments        ← from --type mission-segments
│   Tags: mission, mode, vessel
│   Fields: duration_s, segment_number
│
├── Measurement: navigation              ← from --type navigation
│   Tags: mission, vessel
│   Fields: latitude, longitude, heading, speed
│
└── ... more measurements as new types are added to data-types.json
```

Accessible at http://localhost:8086 (Data Explorer).

### 4. Data Visualization: Grafana

Grafana queries InfluxDB and displays the results.

**Connection path:** Grafana → (docker network `influx-net`) → InfluxDB
**URL used by Grafana:** `http://influxdb:8086` (container name, NOT localhost)

The pie chart query:

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "mission_segments")
  |> filter(fn: (r) => r._field == "duration_s")
  |> filter(fn: (r) => r.mission == "${mission}")        ← from dropdown
  |> group(columns: ["mode"])
  |> sum()
  |> keep(columns: ["mode", "_value"])
  |> group()
```

This sums all `duration_s` values grouped by mode, giving total time spent in each mode.

## Adding a New Mission

```
1. Get new CSV from post-mission analysis

2. Feed it:
   $ node write.js --mission mission-002 --type mission-segments --csv /path/to/new-data.csv

3. Open Grafana → Mission dropdown now shows "mission-002"

4. Select it → pie chart updates automatically

No code changes. No dashboard changes. No provisioning changes.
```

## What Lives Where

```
Your machine (host)
├── ./write.js                          ← you run this
├── ./pm-data/                          ← CSV files
├── ./volumes/influxdb-data/            ← InfluxDB stores data here
├── ./volumes/grafana-data/             ← Grafana state (sessions, etc.)
├── ./provisioning/                     ← dashboard templates (auto-loaded)
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
