# Bar Charts — Battery / Power Consumption

## What These Charts Show

Two bar charts visualizing battery performance per operational mode:

1. **Total Battery Drop by Mode** — how much battery (%) was consumed in each mode across the entire mission
2. **Battery Consumption Rate by Mode** — how fast battery drains per hour in each mode

Both are panels inside the "Mission mode distribution" dashboard alongside the pie chart.

## Data Source

CSV: `pm-data/mission_time_report.xlsx - Power Consumption.csv`

```csv
Mode,Total Battery Drop (%),Duration (hours),Rate (%/hour),Sample Pairs
Direct,0.9999990463,5.797844829,0.1724777182,11910
Idle,-23.50000143,5.09241732,-4.61470456,8202
Navigation,34.0000093,6.159981459,5.519498642,7703
Station,0.4999995232,0.5718625453,0.874335148,1172
Voyage,1.499998569,0.06639174738,22.59314792,136
```

This is **summary data** — 5 rows, one per mode. Not time-series.

## Summary Data vs Time-Series Data

| | Time-series | Summary |
|---|---|---|
| Example | Mission segments (203 rows with timestamps) | Power consumption (5 rows, one per mode) |
| Timestamp | Each row has its own timestamp from CSV | No timestamp column — uses current time when writing |
| `timestamp_column` in data-types.json | `"Start Time"` | `null` |
| Grafana time range | Filters data by actual event time | Just needs to include "today" (when data was fed) |
| How charts use it | Time can be on X-axis | Time is irrelevant — X-axis shows tags (mode names) |

### Why timestamps don't affect bar chart rendering

The Flux query does `keep(columns: ["mode", "_value"])` which strips the timestamp entirely.
Grafana receives just mode names and numbers — that's what it plots.

The timestamp only matters as a filter gate: `range(start: ..., stop: ...)` checks if the data point
falls within the selected time window. If yes, it's included. The actual bar position and height
come from the `mode` tag and field value.

## data-types.json Entry

```json
"power-consumption": {
  "measurement": "power_consumption",
  "timestamp_column": null,
  "tags": {
    "mode": "Mode"
  },
  "fields": {
    "total_battery_drop": { "column": "Total Battery Drop (%)", "type": "float" },
    "duration_hours": { "column": "Duration (hours)", "type": "float" },
    "rate_per_hour": { "column": "Rate (%/hour)", "type": "float" },
    "sample_pairs": { "column": "Sample Pairs", "type": "int" }
  }
}
```

`timestamp_column: null` tells `write.js` to use the current time for all rows.

## Feeding the Data

```bash
node write.js --mission mission-001 --type power-consumption --csv "./pm-data/mission_time_report.xlsx - Power Consumption.csv"
```

## Flux Queries

### Total Battery Drop by Mode

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "power_consumption")
  |> filter(fn: (r) => r._field == "total_battery_drop")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> keep(columns: ["mode", "_value"])
  |> group()
  |> rename(columns: {_value: "Battery Drop (%)"})
```

### Battery Consumption Rate by Mode

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "power_consumption")
  |> filter(fn: (r) => r._field == "rate_per_hour")
  |> filter(fn: (r) => r.mission == "${mission}")
  |> keep(columns: ["mode", "_value"])
  |> group()
  |> rename(columns: {_value: "Rate (%/hour)"})
```

### Key patterns

- `rename(columns: {_value: "..."})` — replaces the default `_value` legend label with something readable
- `keep(columns: ["mode", "_value"])` — strips all metadata, leaving only what the chart needs
- `${mission}` — template variable from the Mission dropdown

## Modifying These Charts

1. Edit the panel in Grafana UI (http://localhost:3000)
2. Save the dashboard (Ctrl+S)
3. Re-export via API:
   ```bash
   curl -s -u admin:admin "http://localhost:3000/api/dashboards/uid/b13d2a0c-4ab2-4a4d-8552-3531e2bc019b" | python3 -m json.tool > /tmp/export.json
   ```
4. Extract and save to provisioning:
   ```bash
   python3 -c "
   import json
   with open('/tmp/export.json') as f:
       data = json.load(f)
   dashboard = data['dashboard']
   del dashboard['id']
   with open('provisioning/dashboards/mission-overview/mode-distribution.json', 'w') as f:
       json.dump(dashboard, f, indent=2)
   "
   ```

## Reading the Charts

### Total Battery Drop
- Positive values = battery drained during that mode
- Negative values = battery charged (e.g., Idle at -23.5% means charging happened)
- Navigation (34%) is the biggest consumer

### Battery Consumption Rate
- Shows drain speed: %/hour
- Voyage is highest (22.59%/hr) but had very little run time (4 min)
- Idle is negative (-4.61%/hr) because battery charges during idle
- Useful for estimating mission endurance per mode
