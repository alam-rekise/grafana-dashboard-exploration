# Project Setup Guide

**Status: Prototype** — see `concepts/project-status.md` for roadmap.

Complete guide to set up the InfluxDB + Grafana mission data visualization pipeline from scratch.

## Prerequisites

- Docker and Docker Compose installed
- Python 3.10+ with `pip3 install influxdb-client` (for ROS bag extraction)
- ROS2 .db3 bag files from a mission
- (Optional) Node.js v18+ for legacy CSV pipeline

## Project Structure

```
influxWithGraphana/
├── docker-compose.yml                          # Runs InfluxDB and Grafana containers
├── write.js                                    # Reads CSV and writes data to InfluxDB
├── package.json                                # Node.js dependencies
├── pm-data/                                    # Place your mission CSV files here
│   └── mission_time_report.xlsx - Mode Segments.csv
├── volumes/                                    # Persistent data (bind mounts)
│   ├── influxdb-data/                          # InfluxDB database files
│   ├── influxdb-config/                        # InfluxDB configuration
│   └── grafana-data/                           # Grafana state (sessions, drafts)
├── provisioning/                               # Grafana auto-configuration (loaded on startup)
│   ├── datasources/
│   │   └── influxdb.yml                        # Auto-configures InfluxDB connection in Grafana
│   └── dashboards/
│       ├── provider.yml                        # Tells Grafana where to find dashboard JSONs
│       └── mission-overview/                   # Folder name → becomes Grafana folder
│           └── mode-distribution.json          # Pie chart dashboard (auto-loaded)
└── concepts/                                   # Documentation and learning notes
```

## Step 1: Install Dependencies

```bash
# For ROS bag extraction (primary pipeline)
pip3 install influxdb-client

# For CSV ingestion (legacy pipeline, optional)
npm install
```

## Step 2: Start the Containers

```bash
docker compose up -d
```

This starts two containers on a shared `influx-net` bridge network:

| Service  | Image                  | Port | URL                    |
| -------- | ---------------------- | ---- | ---------------------- |
| influxdb | influxdb:2.7           | 8086 | http://localhost:8086  |
| grafana  | grafana/grafana:10.1.2 | 3000 | http://localhost:3000  |

### First-time InfluxDB setup

On the very first run, InfluxDB needs initial configuration:

1. Open http://localhost:8086
2. Click "Get Started"
3. Set up:
   - Username: `admin` (or your choice)
   - Password: your choice
   - Organization: `Rekise Marine`
   - Bucket: `vessel-data`
4. Copy the generated API token — you'll need it for `write.js` and `provisioning/datasources/influxdb.yml`

### Grafana credentials

- Default login: `admin` / `admin`
- It will ask you to change the password on first login

## Step 3: Feed Mission Data

### Option A: From ROS Bags (Primary)

```bash
# Single bag file
python3 extract-bag.py --mission rosbag-20260223 --bag /path/to/file.db3

# Entire directory with parallel processing
python3 extract-bag.py --mission rosbag-20260223 --bag-dir /path/to/rosbags/ --workers 8

# Dry run (test without writing)
python3 extract-bag.py --mission test --bag /path/to/file.db3 --dry-run
```

**What extract-bag.py does:**
1. **Pass 1**: Scans `/control_mode/feedback` across all bags to build mode timeline
2. **Pass 2**: Extracts 14 other topics, tags every point with the active mode, writes to InfluxDB
3. Writes 15 measurements, 8M+ points for a full mission (722 bag files, ~68 GB)

See `concepts/rosbag-to-influxdb-extraction.md` for full details.

### Option B: From CSV (Legacy)

```bash
node write.js --mission mission-001 --type mission-segments --csv ./pm-data/mode-segments.csv
```

Config-driven via `data-types.json`. See README for details.

### InfluxDB Data Model

Every data point has three standard tags:
- **mission** → "rosbag-20260223" (separates data per mission)
- **vessel** → "AUV_01"
- **mode** → "Direct", "Idle", "Navigation", "Station", "Voyage" (active mode at that timestamp)

This enables filtering ANY measurement by mode: `filter(fn: (r) => r.mode == "Navigation")`

### Tags vs Fields

- **Tags** are indexed — used for filtering and grouping (WHERE clauses). They're strings.
- **Fields** are the actual measured values — used for aggregation (SUM, MEAN, etc.). They can be numbers.
- Rule of thumb: if you filter by it, make it a tag. If you do math on it, make it a field.

## Step 4: View in Grafana

1. Open http://localhost:3000
2. The "Mission mode distribution" dashboard is **automatically loaded** from provisioning
3. Find it under the **mission-overview** folder in the sidebar
4. Select your mission from the **Mission dropdown** (below dashboard title)
5. Set the **time range** (top right) to cover your data dates (e.g., "Last 7d")

### The Mission Dashboard

4 panels, auto-loaded from provisioning:
1. **Battery consumption rate** — %/hour drain per mode (bar chart)
2. **Total battery drop %** — discharge per mode (bar chart)
3. **Mode distribution** — time in each mode (pie chart)
4. **Mode transitions with battery level** — colored mode backgrounds with battery % line overlay

## Step 5: Adding New Mission Data

```bash
# From ROS bags
python3 extract-bag.py --mission mission-002 --bag-dir /path/to/new-bags/ --workers 8

# Or from CSV
node write.js --mission mission-002 --type mission-segments --csv /path/to/new-data.csv
```

Then in Grafana:
- The "Mission" dropdown automatically picks up the new mission
- Select it → all panels update
- Switch back to the old mission → old data still there

No dashboard changes, no provisioning changes, no restarts needed.

## Common Operations

### Stop everything

```bash
docker compose down
```

Data is safe in `./volumes/` — it will be there when you start again.

### Restart just Grafana (e.g., after changing provisioning files)

```bash
docker compose restart grafana
```

### Delete all InfluxDB data and start fresh

```bash
curl -s -X POST "http://localhost:8086/api/v2/delete?org=Rekise%20Marine&bucket=vessel-data" -H "Authorization: Token <YOUR_TOKEN>" -H "Content-Type: application/json" -d '{"start":"2020-01-01T00:00:00Z","stop":"2030-01-01T00:00:00Z"}'
```

### Export a dashboard from Grafana UI to provisioning

```bash
# 1. Find the dashboard UID
curl -s -u admin:admin "http://localhost:3000/api/search"

# 2. Export the full JSON
curl -s -u admin:admin "http://localhost:3000/api/dashboards/uid/<UID>" | python3 -m json.tool > /tmp/export.json

# 3. Copy only the "dashboard" object (not the "meta" wrapper) to provisioning
# Save to: provisioning/dashboards/<category>/<name>.json
```

### Check what data exists in InfluxDB

Open http://localhost:8086 → Data Explorer → select bucket `vessel-data` → choose time range and filters.

## Troubleshooting

### "No tag keys found in the current time range"

The time range picker doesn't cover your data. Your data has timestamps from the CSV file. Change the time range to cover the dates in your CSV (e.g., if data is from Feb 21, use "Last 7d" or set a custom range).

### "writeApi: already closed!"

You're trying to write data after `writeApi.close()` has been called. This happens if you have a `setInterval` that keeps writing but `close()` runs immediately. Either remove the interval or move `close()` into a shutdown handler.

### Container name conflict on `docker compose up`

Old containers with the same name exist. Remove them first:

```bash
docker rm -f influxdb grafana && docker compose up -d
```

### Dashboard shows no data after provisioning

1. Check the Mission dropdown has values — if empty, data hasn't been fed yet
2. Check the time range covers your data dates
3. Verify the datasource UID in the dashboard JSON matches the one in `provisioning/datasources/influxdb.yml`

### Pie chart legend shows ugly long strings

Add `|> keep(columns: ["mode", "_value"])` and `|> group()` at the end of your Flux query to strip metadata columns.
