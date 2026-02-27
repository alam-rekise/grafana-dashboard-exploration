# InfluxDB + Grafana Mission Data Visualization

**Status: Prototype** (see `concepts/project-status.md` for roadmap)

Automated pipeline for visualizing AUV mission data — extract from ROS bags or CSV, get interactive dashboards.

## Quick Start

```bash
# 1. Start InfluxDB and Grafana
docker compose up -d

# 2. Complete InfluxDB initial setup at http://localhost:8086
#    Create org: "Rekise Marine", bucket: "vessel-data"
#    Save the generated API token

# 3. Install Python dependencies
pip3 install influxdb-client rosbags

# 4. Seed the database from ROS bag files (~10-12 minutes)
python3 extract-bag.py --mission rosbag-20260223 --bag-dir /path/to/rosbags/ --workers 8

# 5. Open Grafana → http://localhost:3000 (admin/admin)
#    Dashboard is auto-loaded. Select mission from dropdown.
#    Set time range to cover your data (e.g., Feb 22-24 for rosbag-20260223).
```

## Seeding the Database

The `volumes/` directory (InfluxDB data) is **not** checked into git — it contains large binary database files that are environment-specific. Instead, the database is seeded from ROS bag files using the extraction script.

### Prerequisites

- Docker and Docker Compose
- Python 3 with `influxdb-client` and `rosbags` packages
- Access to ROS bag files (.db3 format)

### First-Time Setup

1. Start the containers: `docker compose up -d`
2. Open InfluxDB at http://localhost:8086 and complete the onboarding wizard:
   - Organization: `Rekise Marine`
   - Bucket: `vessel-data`
   - Save the API token
3. Update the token in `provisioning/datasources/influxdb.yml` and in `extract-bag.py` if it differs from the default
4. Run the extraction:
   ```bash
   python3 extract-bag.py --mission rosbag-20260223 --bag-dir /path/to/rosbags/ --workers 8
   ```
5. Open Grafana at http://localhost:3000 (admin/admin) — dashboards are auto-loaded via provisioning

### Why It Takes ~10-12 Minutes

The extraction pipeline does more than copy data — for 722 bag files (68 GB), 9.85M data points:

1. **Two-pass architecture:** First pass builds a complete mode timeline from `/control_mode/feedback` (must be sequential — mode transitions span files). Second pass extracts all sensor data and tags every point with the active mode via binary search.
2. **Custom deserialization:** 11 custom Rekise message types (CDR binary → Python objects) for each of the 9.85M points, plus unit conversions (quaternion → heading degrees).
3. **I/O on both ends:** Reading 68 GB of SQLite-backed .db3 files + writing ~2,000 HTTP batches (5,000 points each) to InfluxDB.
4. **Parallel processing:** 8 workers in the second pass (each with own file batch, mode timeline copy, and InfluxDB connection). Without parallelization, the same extraction takes 40+ minutes.

### Subsequent Runs

The script tracks processed files. Re-running skips already-processed bags automatically. Use `--force` to re-process everything.

## Project Structure

```
influxWithGraphana/
│
├── extract-bag.py                  # ROS bag → InfluxDB (primary pipeline, Python)
├── inspect-bag.py                  # Utility: inspect ROS bag contents and message types
├── write.js                        # CSV → InfluxDB (legacy pipeline, Node.js)
├── data-types.json                 # CSV column mappings for write.js
├── docker-compose.yml              # Defines InfluxDB + Grafana containers
├── package.json                    # Node.js dependencies (@influxdata/influxdb-client)
│
├── scripts/
│   └── reset-and-seed.sh          # Wipes InfluxDB data and re-feeds all CSVs for a mission
│
├── panel-templates/                # Reusable Grafana panel JSON templates
│   ├── mode-timeline-with-overlay.json  # Mode blocks + line overlay (combined)
│   ├── bar-chart-battery-drop.json      # Battery drop by mode
│   ├── bar-chart-consumption-rate.json  # Consumption rate by mode
│   ├── temperature-over-time.json       # Temperature with mode backgrounds
│   ├── state-timeline.json              # Categorical state blocks
│   └── time-series-line.json            # Generic line chart
│
├── pm-data/                        # Mission CSV files (legacy input data)
│
├── provisioning/                   # Grafana auto-configuration (dashboards + datasources)
│   ├── datasources/
│   │   └── influxdb.yml            # InfluxDB connection config
│   └── dashboards/
│       ├── provider.yml            # Dashboard provider config (auto-reload every 10s)
│       └── mission-overview/       # Folder name → becomes Grafana folder
│           └── mode-distribution.json  # Dashboard: 8 panels (mission time analysis)
│
├── volumes/                        # Persistent data (bind-mounted into containers)
│   ├── influxdb-data/              # InfluxDB database files
│   ├── influxdb-config/            # InfluxDB server configuration
│   └── grafana-data/               # Grafana runtime state
│
├── benchmarking/                   # Extraction performance benchmarks
│
└── concepts/                       # Documentation
    ├── project-status.md           # Current phase, roadmap, known limitations
    ├── project-setup-guide.md      # Step-by-step setup for new developers
    ├── data-pipeline-flow.md       # Architecture: ROS bag / CSV → InfluxDB → Grafana
    ├── rosbag-to-influxdb-extraction.md  # extract-bag.py: two-pass approach, measurements, queries
    ├── rosbag-field-mapping.md     # ROS topics → InfluxDB measurements mapping
    ├── mode-timeline-panel.md      # Combined mode+battery panel implementation
    ├── heading-comparison-panel.md # 3 heading sources, quaternion conversion, multi-line technique
    ├── leak-detection-panel.md     # Leak sensor panel, value mappings, step interpolation
    ├── data-verification-audit.md  # Full data audit: counts, rates, distributions, findings
    ├── bar-charts.md               # Battery bar charts: difference() and join queries
    ├── docker-compose-explained.md # docker-compose.yml breakdown
    ├── docker-volumes.md           # Volume types: anonymous, named, bind mounts
    ├── grafana-provisioning.md     # How Grafana auto-loads config from files
    ├── grafana-template-variables.md # Time picker vs template variable dropdowns
    └── influxdb-basics.md          # Buckets, measurements, tags vs fields, Flux queries
```

## File Descriptions

### Core Files

| File | Purpose |
| ---- | ------- |
| `extract-bag.py` | **Primary pipeline.** Reads ROS2 .db3 bag files and writes 16 measurements to InfluxDB. Two-pass: builds mode timeline, then extracts all sensor data with mode tags. Supports parallel processing. |
| `inspect-bag.py` | Utility for inspecting ROS bag contents — lists topics, message types, message counts, and sample field values. |
| `docker-compose.yml` | Runs InfluxDB (port 8086) and Grafana (port 3000) on a shared Docker network. Uses bind mounts for persistent storage and provisioning. |
| `write.js` | Legacy CSV ingestion script. Config-driven via `data-types.json`. Usage: `node write.js --mission <name> --type <type> --csv <path>` |
| `data-types.json` | Defines CSV column → InfluxDB mappings for write.js. Add new entries to support new CSV formats. |

### Provisioning Files

Auto-loaded by Grafana on startup — no manual UI setup needed.

| File | Purpose |
| ---- | ------- |
| `provisioning/datasources/influxdb.yml` | InfluxDB datasource config (URL, token, org, bucket). Grafana connects via Docker network at `http://influxdb:8086`. |
| `provisioning/dashboards/provider.yml` | Dashboard provider config. Auto-reloads every 10s. `foldersFromFilesStructure: true` maps subdirectories to Grafana folders. |
| `provisioning/dashboards/mission-overview/mode-distribution.json` | Dashboard with 8 panels: mode distribution (pie), total battery drop (bar), consumption rate (bar), mode timeline with battery level, temperature over time, humidity over time, heading comparison (3 sources), leak detection. |

### Panel Templates

Reusable panel configs in `panel-templates/`. Copy into any dashboard and update queries.

| File | Purpose |
| ---- | ------- |
| `mode-timeline-with-overlay.json` | Colored mode backgrounds with numeric line overlaid (combined time series panel) |
| `bar-chart-battery-drop.json` | Total battery drop by mode (difference query) |
| `bar-chart-consumption-rate.json` | Battery consumption rate %/hour (join query) |
| `state-timeline.json` | Categorical state timeline (colored blocks) |
| `time-series-line.json` | Generic time series line chart |
| `temperature-over-time.json` | Temperature with mode-colored backgrounds |

### Concepts (Documentation)

| File | What It Covers |
| ---- | -------------- |
| `project-status.md` | **Start here.** Current phase (prototype), roadmap to MVP and production, known limitations. |
| `project-setup-guide.md` | Step-by-step setup: prerequisites, Docker, feeding data, viewing dashboards, troubleshooting. |
| `data-pipeline-flow.md` | Architecture: ROS bag and CSV pipelines → InfluxDB → Grafana. Network topology. File locations. |
| `rosbag-to-influxdb-extraction.md` | extract-bag.py deep dive: two-pass approach, custom message types, all 16 measurements, Grafana queries. |
| `rosbag-field-mapping.md` | ROS topics → dashboard requirements mapping. Which topics feed which charts. |
| `mode-timeline-panel.md` | Combined mode+battery panel: stacked area trick, query structure, color scheme, tooltip limitations. |
| `bar-charts.md` | Battery bar charts: why difference() not first-to-last, why join not reduce, mid-mission charging. |
| `docker-compose-explained.md` | docker-compose.yml breakdown: services, ports, volumes, networks. |
| `docker-volumes.md` | Docker storage: anonymous vs named volumes vs bind mounts. |
| `grafana-provisioning.md` | How Grafana auto-loads config. Current provisioned dashboards. Workflow for editing. |
| `grafana-template-variables.md` | Time picker vs template variables. Mission dropdown implementation. |
| `heading-comparison-panel.md` | Heading comparison panel: 3 heading sources, quaternion-to-degrees conversion, multi-line panel technique. |
| `leak-detection-panel.md` | Leak detection panel: status values, step interpolation, value mappings. |
| `data-verification-audit.md` | Full data audit: point counts, sample rates, value distributions, critical findings (GNSS constant 90°, missing mission-001 data). |
| `influxdb-basics.md` | Buckets, measurements, tags vs fields, Flux queries. |

## Feeding Data

### Pipeline 1: ROS Bag Extraction (Primary)

```bash
# Prerequisites
pip3 install influxdb-client

# Single bag file
python3 extract-bag.py --mission rosbag-20260223 --bag /path/to/file.db3

# Entire directory (parallel)
python3 extract-bag.py --mission rosbag-20260223 --bag-dir /path/to/rosbags/ --workers 8

# Dry run (process without writing to InfluxDB)
python3 extract-bag.py --mission test --bag /path/to/file.db3 --dry-run

# Force re-process (ignore tracking)
python3 extract-bag.py --mission rosbag-20260223 --bag-dir /path/to/rosbags/ --force --workers 8
```

Writes 16 measurements to InfluxDB. Every point tagged with `mission`, `vessel`, and `mode`.
See `concepts/rosbag-to-influxdb-extraction.md` for details.

### Pipeline 2: CSV Ingestion (Legacy)

```bash
npm install
node write.js --mission <mission-name> --type <data-type> --csv <path-to-csv>
```

Config-driven via `data-types.json`. Available types:

| Type | Measurement | Description |
| ---- | ----------- | ----------- |
| `mission-segments` | `mission_segments` | Mode segments with duration |
| `power-consumption` | `power_consumption` | Battery stats per mode (summary) |
| `navigation` | `navigation` | GPS/navigation data (placeholder) |

Edit `data-types.json` to add new CSV types — no code changes to `write.js` needed.

## Adding New Dashboards

All dashboards query the **same data** in InfluxDB. You don't re-feed data for new dashboards.

1. Build the dashboard in Grafana UI (http://localhost:3000)
2. Save it
3. Export via API:
   ```bash
   # Find the dashboard UID
   curl -s -u admin:admin "http://localhost:3000/api/search"

   # Export the JSON (replace <UID>)
   curl -s -u admin:admin "http://localhost:3000/api/dashboards/uid/<UID>" | python3 -m json.tool > /tmp/export.json
   ```
4. From the exported JSON, take only the `"dashboard"` object (strip the `"meta"` wrapper)
5. Save to `provisioning/dashboards/<category>/<name>.json`
6. Restart Grafana: `docker compose restart grafana`

Example — adding new dashboards:
```
provisioning/dashboards/
├── provider.yml
├── mission-overview/
│   ├── mode-distribution.json      # existing pie chart
│   └── mode-timeline.json          # new bar chart
└── vessel-performance/
    └── speed-depth.json            # new category + dashboard
```

## Common Commands

| Command | What It Does |
| ------- | ------------ |
| `docker compose up -d` | Start everything in background |
| `docker compose down` | Stop everything (data safe in ./volumes/) |
| `docker compose restart grafana` | Restart Grafana (picks up provisioning changes) |
| `docker compose logs -f` | Follow live logs from all services |
| `node write.js --mission <name> --type <type> --csv <path>` | Feed data from a CSV |
