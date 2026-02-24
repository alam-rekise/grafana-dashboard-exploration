# InfluxDB Basics

## What Is InfluxDB?

InfluxDB is a time-series database — optimized for storing data that has a timestamp.
Examples: sensor readings, server metrics, mission telemetry, stock prices.

## Key Concepts

### Bucket

A bucket is where data is stored. Similar to a "database" in SQL.
Our bucket: `vessel-data`

### Measurement

A measurement is like a "table" in SQL. It groups related data points.
Our measurement: `mission_segments`

### Tags

Tags are **indexed metadata** used for filtering and grouping.
They are always strings. Think of them as labels on your data.

```
mission = "mission-001"    ← which mission
mode = "Direct"            ← operational mode
vessel = "AUV_01"          ← which vessel
```

Tags are fast to query because they're indexed. Use tags for anything you filter by
(`WHERE mission = "mission-001"`).

### Fields

Fields are the **actual measured values**. They can be integers, floats, strings, or booleans.
Fields are NOT indexed — you can't efficiently filter by them, but you can do math on them.

```
duration_s = 19041.95      ← how long the segment lasted (float)
segment_number = 1         ← which segment (integer)
```

### Timestamp

Every data point has a timestamp. This is what makes it a "time-series" database.
We use millisecond precision, derived from the CSV's "Start Time" column.

### Tags vs Fields — When to Use Which

| Use a Tag when...              | Use a Field when...               |
| ------------------------------ | --------------------------------- |
| You filter/group by it         | You do math on it (SUM, AVG)      |
| It has low cardinality         | It has high cardinality            |
| It categorizes data            | It's the actual measured value     |
| Example: mode, mission, vessel | Example: duration_s, segment_number |

**Cardinality** = number of unique values. Tags with high cardinality (thousands of unique values)
hurt performance because InfluxDB indexes every unique tag combination.

## Flux Query Language

InfluxDB v2 uses Flux for querying. It's a pipe-based language where data flows through transformations.

### Basic Query Structure

```flux
from(bucket: "vessel-data")                                    // 1. Start from bucket
  |> range(start: -7d)                                         // 2. Time range filter
  |> filter(fn: (r) => r._measurement == "mission_segments")   // 3. Filter measurement
  |> filter(fn: (r) => r._field == "duration_s")               // 4. Filter field
  |> filter(fn: (r) => r.mission == "mission-001")             // 5. Filter by tag
```

Each `|>` pipes data to the next function. Think of it like Unix pipes (`|`).

### Common Operations

```flux
// Sum durations grouped by mode
|> group(columns: ["mode"])
|> sum()

// Keep only specific columns (cleans up metadata)
|> keep(columns: ["mode", "_value"])

// Ungroup (merge all tables into one)
|> group()
```

### Understanding Tables in Flux

Flux returns data as "tables". Each unique combination of tags creates a separate table.
For example, if you have 6 modes and 2 missions, you get 12 tables.

The `group()` function controls how data is split into tables:
- `group(columns: ["mode"])` → one table per mode
- `group()` with no args → merge everything into one table

### Grafana Variables in Flux

When using Grafana, you can reference dashboard variables and time range:

```flux
from(bucket: "vessel-data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)  // Grafana time picker
  |> filter(fn: (r) => r.mission == "${mission}")            // Grafana template variable
```

## Writing Data with Node.js

The `@influxdata/influxdb-client` library provides:

```javascript
const point = new Point("mission_segments")   // measurement
  .tag("mission", "mission-001")              // tag
  .tag("mode", "Direct")                      // tag
  .floatField("duration_s", 19041.95)         // field
  .intField("segment_number", 1)              // field
  .timestamp(1771630239000);                  // timestamp in ms

writeApi.writePoint(point);
```

### Write Precision

When creating the writeApi, you specify timestamp precision:

```javascript
client.getWriteApi(org, bucket, "ms");  // milliseconds
// Other options: "ns" (nanoseconds), "us" (microseconds), "s" (seconds)
```

### Closing the WriteApi

Always call `writeApi.close()` when done. This flushes any buffered points to InfluxDB.
Not closing means data may be lost.

```javascript
writeApi.close()
  .then(() => console.log("Done!"))
  .catch((e) => console.error("Failed:", e));
```

## Deleting Data

Use the HTTP API to delete data within a time range:

```bash
curl -s -X POST "http://localhost:8086/api/v2/delete?org=Rekise%20Marine&bucket=vessel-data" \
  -H "Authorization: Token <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"start":"2020-01-01T00:00:00Z","stop":"2030-01-01T00:00:00Z"}'
```

You can also add a `predicate` to delete selectively:

```json
{
  "start": "2020-01-01T00:00:00Z",
  "stop": "2030-01-01T00:00:00Z",
  "predicate": "_measurement=\"mission_segments\" AND mission=\"mission-001\""
}
```
