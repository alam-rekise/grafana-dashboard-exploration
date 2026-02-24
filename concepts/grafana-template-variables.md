# Grafana Template Variables

## What Are Template Variables?

Template variables add interactive dropdowns to your dashboard that let you
filter data dynamically without editing queries manually.

## Types of Dropdowns in Grafana

### Time Picker (built-in, top right)

- Controls the time range: "Last 1h", "Last 7d", custom range, etc.
- Feeds `v.timeRangeStart` and `v.timeRangeStop` into Flux queries
- Always present on every dashboard

### Template Variables (custom, below dashboard title)

- Added by you via Dashboard Settings → Variables
- Appear as dropdowns below the dashboard title bar
- Referenced in queries as `${variableName}`
- Example: a "mission" dropdown that lists all available missions

## How They Work Together

```
[Mission: mission-001 ▼]                         [Last 7 days ▼]
 ^^^^^^^^^^^^^^^^^^^^^^^^                         ^^^^^^^^^^^^^^^
 Template variable                                Time picker
 Filters by mission tag                           Filters by time range
 (below dashboard title)                          (top right corner)
```

Both filters apply to the same query:

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)   // ← time picker
  |> filter(fn: (r) => r.mission == "${mission}")             // ← template variable
```

## Creating a Template Variable

1. Dashboard Settings (gear icon) → Variables → New Variable
2. Name: `mission`
3. Type: Query
4. Query: Flux query that returns distinct mission tag values
5. The dropdown auto-populates from InfluxDB data

## Key Benefit

One dashboard template works for ALL missions. When new data is written
with a new mission tag, the dropdown automatically picks it up.
No new dashboards or provisioning changes needed.

## In Provisioning JSON

Template variables are stored in the `templating.list` array of the
dashboard JSON. When you export and provision the dashboard, the
variable definition is included — so it works automatically on fresh deployments.
