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

## Workflow

1. Design dashboard in Grafana UI
2. Export via API: `curl -s -u admin:admin "http://localhost:3000/api/dashboards/uid/<UID>"`
3. Save JSON to `provisioning/dashboards/<category>/<name>.json`
4. Strip the `meta` wrapper — only keep the `dashboard` object contents
5. Now the dashboard is reproducible and git-trackable
