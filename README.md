# InfluxDB + Grafana Mission Data Visualization

Automated pipeline for visualizing AUV mission data — feed a CSV, get interactive dashboards.

## Quick Start

```bash
# 1. Install dependencies
npm install

# 2. Start InfluxDB and Grafana
docker compose up -d

# 3. Feed mission data
node write.js --mission mission-001 --type mission-segments --csv ./pm-data/your-file.csv

# 4. Open Grafana → http://localhost:3000 (admin/admin)
#    Dashboard is auto-loaded. Select mission from dropdown. Set time range to cover your data.
```

## Project Structure

```
influxWithGraphana/
│
├── docker-compose.yml              # Defines InfluxDB + Grafana containers
├── write.js                        # CSV → InfluxDB ingestion script (config-driven)
├── data-types.json                 # Defines how each CSV type maps to InfluxDB (measurements, tags, fields)
├── package.json                    # Node.js dependencies (@influxdata/influxdb-client)
│
├── pm-data/                        # Mission CSV files (input data)
│
├── provisioning/                   # Grafana auto-configuration (dashboards + datasources)
│   ├── datasources/
│   │   └── influxdb.yml            # InfluxDB connection config (auto-loaded on Grafana startup)
│   └── dashboards/
│       ├── provider.yml            # Tells Grafana to scan this directory for dashboard JSONs
│       └── mission-overview/       # Folder name → becomes a folder in Grafana sidebar
│           └── mode-distribution.json  # Pie chart: time spent in each operational mode
│
├── volumes/                        # Persistent data (bind-mounted into containers)
│   ├── influxdb-data/              # InfluxDB database files (measurements, indexes)
│   ├── influxdb-config/            # InfluxDB server configuration
│   └── grafana-data/               # Grafana runtime state (user sessions, UI drafts)
│
└── concepts/                       # Documentation and learning notes
    ├── project-setup-guide.md      # Step-by-step setup for new developers
    ├── data-pipeline-flow.md       # End-to-end architecture: CSV → InfluxDB → Grafana
    ├── docker-compose-explained.md # docker-compose.yml breakdown line by line
    ├── docker-volumes.md           # Volume types: anonymous, named, bind mounts
    ├── grafana-provisioning.md     # How Grafana auto-loads datasources and dashboards
    ├── grafana-template-variables.md # Time picker vs template variable dropdowns
    └── influxdb-basics.md          # Buckets, measurements, tags vs fields, Flux queries
```

## File Descriptions

### Core Files

| File | Purpose |
| ---- | ------- |
| `docker-compose.yml` | Runs InfluxDB (port 8086) and Grafana (port 3000) on a shared Docker network. Uses bind mounts for persistent storage and provisioning. |
| `write.js` | Config-driven CSV ingestion script. Reads `data-types.json` to understand how to parse any CSV format. Usage: `node write.js --mission <name> --type <type> --csv <path>` |
| `data-types.json` | Defines all supported data types. Each entry maps CSV column names to InfluxDB measurements, tags, and fields. Add new entries here to support new CSV formats — no code changes needed. |
| `package.json` | Declares the `@influxdata/influxdb-client` dependency for writing data to InfluxDB from Node.js. |

### Provisioning Files

These files are auto-loaded by Grafana on startup — no manual UI setup needed.

| File | Purpose |
| ---- | ------- |
| `provisioning/datasources/influxdb.yml` | Configures the InfluxDB datasource in Grafana (URL, token, org, bucket). Uses Flux query language. Grafana connects to InfluxDB via Docker network at `http://influxdb:8086`. |
| `provisioning/dashboards/provider.yml` | Tells Grafana to scan for JSON dashboard files in this directory. `foldersFromFilesStructure: true` means subdirectory names become Grafana folders. |
| `provisioning/dashboards/mission-overview/mode-distribution.json` | Pie chart dashboard showing time distribution across operational modes (Direct, Idle, Navigation, Station, Voyage, NO_BAG_RECORD). Includes a "Mission" dropdown variable for filtering by mission. |

### Data Directories

| Directory | Purpose |
| --------- | ------- |
| `pm-data/` | Place mission CSV files here. Any CSV format is supported as long as it has a matching entry in `data-types.json`. |
| `volumes/influxdb-data/` | InfluxDB database storage. Contains the actual time-series data. Persists across container restarts. |
| `volumes/influxdb-config/` | InfluxDB server configuration files. |
| `volumes/grafana-data/` | Grafana runtime state — user sessions, draft dashboards, alerting config. Not critical (provisioning recreates dashboards). |

### Concepts (Documentation)

| File | What It Covers |
| ---- | -------------- |
| `concepts/project-setup-guide.md` | Full walkthrough for new developers: prerequisites, setup, feeding data, viewing dashboards, troubleshooting. |
| `concepts/data-pipeline-flow.md` | Architecture diagram: how data flows from CSV → write.js → InfluxDB → Grafana. Network topology. What lives where. |
| `concepts/docker-compose-explained.md` | Line-by-line explanation of docker-compose.yml: services, ports, volumes, networks. Why Grafana uses `http://influxdb:8086` not localhost. |
| `concepts/docker-volumes.md` | Docker storage: anonymous vs named volumes vs bind mounts. What happens on container removal. |
| `concepts/grafana-provisioning.md` | How Grafana auto-loads config from files. Provisioning vs volumes. Workflow for exporting dashboards. |
| `concepts/grafana-template-variables.md` | Time picker vs template variables. How the Mission dropdown works. How variables are stored in JSON. |
| `concepts/influxdb-basics.md` | InfluxDB concepts: buckets, measurements, tags vs fields, Flux queries, writing data with Node.js. |

## Feeding Data

### Usage

```bash
node write.js --mission <mission-name> --type <data-type> --csv <path-to-csv>
```

### Available Data Types

Run `node write.js` with no arguments to see all available types.

Currently defined in `data-types.json`:

| Type | Measurement | Description |
| ---- | ----------- | ----------- |
| `mission-segments` | `mission_segments` | Mode segments (Direct, Idle, Navigation, etc.) with duration |
| `navigation` | `navigation` | GPS/navigation data (latitude, longitude, heading, speed) |

### Examples

```bash
# Feed mission mode segments
node write.js --mission mission-001 --type mission-segments --csv ./pm-data/mode-segments.csv

# Feed navigation data
node write.js --mission mission-001 --type navigation --csv ./pm-data/nav-data.csv

# Both data types share the same mission tag, so Grafana can filter by mission across all data
```

### Adding a New Data Type

Edit `data-types.json` and add a new entry:

```json
{
  "depth-telemetry": {
    "measurement": "depth_telemetry",
    "timestamp_column": "Timestamp",
    "tags": {},
    "fields": {
      "depth": { "column": "Depth (m)", "type": "float" },
      "pressure": { "column": "Pressure (bar)", "type": "float" },
      "temperature": { "column": "Temp (C)", "type": "float" }
    }
  }
}
```

Then feed it:

```bash
node write.js --mission mission-001 --type depth-telemetry --csv ./pm-data/depth.csv
```

No code changes to `write.js` needed. The config drives everything.

### How data-types.json Works

Each entry defines:

| Key | Purpose |
| --- | ------- |
| `measurement` | InfluxDB measurement name (like a table name) |
| `timestamp_column` | Which CSV column contains the timestamp |
| `tags` | CSV columns to use as InfluxDB tags (indexed, for filtering). Format: `{ "tag_name": "CSV Column Name" }` |
| `fields` | CSV columns to use as InfluxDB fields (values, for math). Format: `{ "field_name": { "column": "CSV Column Name", "type": "int\|float\|string" } }` |

The `mission` and `vessel` tags are always added automatically — you don't need to define them.

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
