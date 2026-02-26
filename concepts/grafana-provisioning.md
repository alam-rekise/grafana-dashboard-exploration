# Grafana Provisioning

## What Is Provisioning?

Provisioning lets you define Grafana configuration (datasources, dashboards) as files
that get auto-loaded on startup — no manual UI setup needed.

## How It Works

### On Startup

1. Grafana reads YAML files from `/etc/grafana/provisioning/datasources/` → creates datasource connections
2. Grafana reads YAML files from `/etc/grafana/provisioning/dashboards/` → finds a provider config
3. The provider config points to a directory containing JSON dashboard files
4. Grafana loads all JSON dashboards from that directory (recursively)

### Directory Structure

```
provisioning/
├── datasources/
│   └── influxdb.yml              # defines the InfluxDB connection
└── dashboards/
    ├── provider.yml              # tells Grafana where to find JSON files
    └── mission-overview/         # becomes a folder in Grafana UI
        └── mode-distribution.json
```

### Key Option: foldersFromFilesStructure

When `foldersFromFilesStructure: true` in provider.yml, subdirectory names
become folder names in Grafana. So `mission-overview/` directory creates a
"mission-overview" folder in the Grafana sidebar.

## Provisioning vs Volumes

| Concern                            | Provisioning                         | Volume                                         |
| ---------------------------------- | ------------------------------------ | ---------------------------------------------- |
| What it stores                     | Dashboard structure, queries, layout | Runtime state, user sessions, draft dashboards |
| Survives `docker compose down -v`? | Yes (lives in your project files)    | No (deleted with volumes)                      |
| Version controllable (git)?        | Yes                                  | No                                             |
| Editable via UI?                   | Yes if `allowUiUpdates: true`        | N/A                                            |

## Provisioning Does NOT Store Data

Provisioning only defines the dashboard template (panels, queries, variables).
Actual data lives in InfluxDB. The dashboard queries InfluxDB at runtime.

## Current Provisioned Dashboards

### mission-overview/mode-distribution.json
**UID:** `b13d2a0c-4ab2-4a4d-8552-3531e2bc019b`
**Panels:**
1. Battery consumption rate (bar chart) — %/hour drain per mode via join query
2. Total battery drop % (bar chart) — discharge per mode via difference() query
3. Mode distribution (pie chart) — time in each mode from mission_segments
4. Mode transitions with battery level (time series) — colored mode backgrounds + battery % line
5. Temperature over time (time series) — colored mode backgrounds + temperature line (right axis 20-45°C)

**Template variable:** `${mission}` — populated from `schema.tagValues(bucket: "vessel-data", tag: "mission")`

## Workflow

### Editing provisioned dashboards directly:
Since `allowUiUpdates: true`, you can edit in the Grafana UI. But changes in UI don't persist — the file on disk is the source of truth. Edit the JSON file directly, and Grafana auto-reloads every 10 seconds.

### Creating new dashboards from templates:
1. Copy a panel template from `panel-templates/` into a new dashboard JSON
2. Replace `${DS_INFLUXDB}` with your datasource UID (or use Grafana's import with datasource mapping)
3. Update queries for your data
4. Save to `provisioning/dashboards/<folder-name>/<dashboard-name>.json`
5. Grafana picks it up automatically

### Exporting from UI (if needed):
1. `curl -s -u admin:admin "http://localhost:3000/api/dashboards/uid/<UID>"`
2. Extract `dashboard` object (strip `meta` wrapper, remove `id` field)
3. Save to provisioning directory
