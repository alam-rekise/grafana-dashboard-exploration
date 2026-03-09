# Live Vessel Data → InfluxDB: Approaches

## Goal

Stream vessel sensor data directly into InfluxDB in real-time instead of extracting from bag files post-mission. This enables live dashboards and threshold-based alerting (e.g., email on high temperature, low battery, leak detected).

---

## Current Pipeline (Batch/Offline)

```
ros2 bag record → .db3 bag files → extract-bag.py → InfluxDB → Grafana
```

- Data is recorded on the vessel using `ros2 bag record` which subscribes to ROS2 topics and saves them as .db3 files
- 722 bag files (68 GB), 9.85M data points, 16 measurements extracted so far
- Two-pass extraction: mode timeline first, then sensor data
- All processing happens after the mission is complete — no live visibility

---

## Key Insight: ROS2 Supports Multiple Subscribers

ROS2 uses DDS (Data Distribution Service) as its middleware, which natively supports **multiple subscribers on the same topic**. This means `ros2 bag record` and a live InfluxDB writer can run simultaneously — both subscribe to the same topics, each gets every message independently. No changes to the recording command or vessel software are needed.

```
                        ┌→ ros2 bag record (continues saving .db3 files as backup)
Vessel ROS2 Topics ─────┤
                        └→ influxdb_writer node (writes to InfluxDB in real-time)
```

This is not a hack — it's how ROS2's pub-sub model is designed to work. Adding a subscriber has negligible overhead on publishers; DDS handles multicast delivery at the middleware level.

---

## Approach 1: ROS2 Subscriber Node → InfluxDB (Recommended for Prototype)

### How It Works

A Python ROS2 node runs alongside `ros2 bag record`, subscribing to the same live topics (`/temperature`, `/battery_state`, `/telemetry/state`, `/leak_detect`, etc.). On each message, it converts the data to an InfluxDB point and writes it directly.

```
                        ┌→ ros2 bag record (backup, unchanged)
Vessel ROS2 Topics ─────┤
                        └→ influxdb_writer_node → influxdb-client-python → InfluxDB → Grafana
```

The writer node can be launched alongside the bag recorder — either manually or in the same ROS2 launch file.

### Why This Makes Sense for Us

- We already have all 15 topic processors written in `extract-bag.py` — the message parsing, field extraction, and InfluxDB point creation logic can be reused directly
- Minimal new infrastructure — just one additional ROS2 node running in parallel with `ros2 bag record`
- Bag recording continues as-is for archival/backup — zero risk to existing workflow

### Performance Data

- **influxdb-client-python** (v1.50.0, actively maintained) supports three write modes:
  - SYNCHRONOUS: blocks until write completes, easiest error handling
  - BATCHING: accumulates points, sends in batches (default: 1,000 points or every 1 second)
  - ASYNCHRONOUS: non-blocking writes
- Default batch config: 1,000 points per batch, 1s flush interval, 5 retries with exponential backoff
- **Optimal batch size for InfluxDB 2.x: 5,000 lines of line protocol** (InfluxData recommendation)
- **Line protocol is ~2x faster than JSON** for writes
- **Gzip compression provides up to 5x speed improvement**

For our use case (~15 topics, most publishing at 1-50 Hz), we're looking at roughly 200-1,000 points/second — well within what a single Python writer can handle.

### InfluxDB 2.x Write Capacity Reference

| Hardware | Writes/sec | Unique Series |
|----------|-----------|---------------|
| 2-4 cores, 2-4 GB RAM | < 5,000 | < 100,000 |
| 4-6 cores, 8-32 GB RAM | < 250,000 | < 1,000,000 |
| 8+ cores, 32+ GB RAM | > 250,000 | > 1,000,000 |

Our server can comfortably handle our data rate.

### Existing ROS2 Packages That Do This

| Package | What It Does | Status |
|---------|-------------|--------|
| `diagnostic_remote_logging` (ROS official) | Subscribes to `/diagnostics_agg`, batches and writes to InfluxDB v2 | Released ROS package, actively maintained |
| `ros2_monitor_grafana` | Monitors ROS2 topic rates (Hz), writes to InfluxDB, displays in Grafana | Active, Python-based |
| `ros2_data_collection` | Full data collection framework using Fluent Bit backend, supports InfluxDB | Active, production-grade |
| `ros2_diag2influxdb` | Stores ROS2 diagnostics in InfluxDB | Smaller project |

### Pros
- Lowest latency (~1-5ms to local InfluxDB)
- Simplest architecture (single additional node)
- Reuses our existing message processing code
- Full control over what data gets written and how

### Cons
- Must run on a machine with access to the vessel's ROS2 network
- No built-in offline resilience (if InfluxDB is unreachable, data is lost unless we add buffering)
- Tight coupling: ROS2 node must know InfluxDB connection details

---

## Approach 2: ROS2 → MQTT Bridge → Telegraf → InfluxDB (Best for Production)

### How It Works

Same parallel subscriber principle — mqtt_client runs alongside `ros2 bag record`, subscribing to the same topics.

```
                        ┌→ ros2 bag record (backup, unchanged)
Vessel ROS2 Topics ─────┤
                        └→ mqtt_client → MQTT Broker → Telegraf mqtt_consumer → InfluxDB → Grafana
```

### Components

**mqtt_client (ika-rwth-aachen)** — the most mature ROS2-MQTT bridge:
- Written in C++ as a ROS2 component node
- Supports ROS2 Humble, Jazzy, Kilted, Rolling
- Bi-directional bridging with arbitrary ROS message types
- Configurable MQTT QoS (0, 1, 2) and ROS QoS profiles
- Built-in latency measurement
- Supports TLS/SSL, auth, message buffering when disconnected
- Local network overhead: single-digit milliseconds

**Telegraf MQTT Consumer Plugin**:
- Subscribes to MQTT topics, parses payloads (JSON, line protocol, CSV)
- Forwards to InfluxDB output plugin
- Default batching: 1,000 metrics per write, 10s flush interval, 10,000 metric buffer
- Throughput: 5,000+ messages/second easily with QoS 2
- 40+ processor plugins for data transformation (rename, filter, aggregate)

**MQTT Broker Options**:

| Broker | Throughput | Notes |
|--------|-----------|-------|
| Mosquitto | ~37,000 msg/sec | Lightweight, single-threaded, good for our scale |
| EMQX | 100,000+ msg/sec | Enterprise-grade, clustering support |

### Why Consider This

- **Decoupled**: ROS2 only talks to MQTT, InfluxDB only talks to Telegraf — each component is independent
- **Offline resilient**: MQTT broker queues messages in persistent sessions; Telegraf buffers metrics if InfluxDB is down
- **Multi-consumer**: MQTT broker allows multiple subscribers — the same data can feed InfluxDB, a logging system, and other services simultaneously
- **No custom code for ingestion**: purely config-driven from MQTT broker onward

### Note on Telegraf ROS2 Plugin

There is **no native Telegraf ROS2 input plugin**. GitHub issue #4692 has been open since 2018 with no development. The MQTT bridge approach is the community-accepted workaround.

### Pros
- Full decoupling between ROS2 and data storage
- Offline resilience (MQTT QoS + broker persistence + Telegraf buffering)
- Multi-consumer support
- Telegraf handles batching, retries, and data transformation
- ROS-agnostic from the broker onward

### Cons
- Highest complexity — 3 services to deploy and configure (mqtt_client, MQTT broker, Telegraf)
- Higher latency than direct write (~5-50ms locally)
- More moving parts to monitor and maintain

---

## Approach 3: Incremental Bag File Processing (Quickest to Implement)

### How It Works

`ros2 bag record` continues writing .db3 files as usual. A watcher script detects when new bag files are completed and triggers `extract-bag.py` to process and ingest them.

```
ros2 bag record → .db3 files → watcher (inotify/polling) → extract-bag.py → InfluxDB → Grafana
```

No parallel subscriber needed — this approach works with the existing bag files after they're written.

### Why Consider This
- **Absolutely zero changes to vessel software** — `ros2 bag record` runs exactly as it does today
- **Uses our existing pipeline exactly as-is** — `extract-bag.py` already handles incremental processing with file tracking
- **Simplest to implement** — just a wrapper script with file watching

### Pros
- No changes to vessel ROS2 nodes
- Proven pipeline (already processed 9.85M points successfully)
- Built-in deduplication (tracker skips already-processed files)

### Cons
- **Not real-time** — delayed by bag file rotation interval (typically 30s to several minutes)
- Depends on bag file being closed before processing (can't read an open bag)
- Alerts will fire late (after bag is written, not when event occurs)

---

## Comparison Summary

| Factor | Direct Write | MQTT + Telegraf | Bag File Watcher |
|--------|-------------|----------------|-----------------|
| **Latency** | ~1-5ms | ~5-50ms | Minutes (bag rotation) |
| **Complexity** | Low (1 new node) | High (3 new services) | Very Low (1 script) |
| **Code Reuse** | High (reuse processors) | Medium (need MQTT config) | Full (existing pipeline) |
| **Offline Resilience** | None by default | MQTT QoS + broker + Telegraf buffer | Inherent (bags are files) |
| **Vessel Changes** | New ROS2 node | New ROS2 node (mqtt_client) | None |
| **Real-time Alerting** | Yes | Yes | No (delayed) |
| **Multi-consumer** | No | Yes (MQTT fan-out) | No |
| **Production Readiness** | Prototype-ready | Production-ready | Stopgap solution |

---

## Recommendation

### Phase 1 (Now): Approach 3 — Bag File Watcher
- Quickest win, no vessel changes needed
- Gets data flowing to dashboards with minimal delay
- Good enough for post-mission review and next-day analysis

### Phase 2 (Short-term): Approach 1 — Direct ROS2 Subscriber
- Reuse extract-bag.py processors in a live ROS2 node
- Enables real-time dashboards and alerting
- Good for controlled testing and demo environments

### Phase 3 (Production): Approach 2 — MQTT Bridge + Telegraf
- When reliability and multi-consumer support become requirements
- When operating in unreliable network conditions (shore-to-vessel link)
- When other systems also need the live data stream

---

## What's Needed to Proceed

1. Confirm which machine will run the ingestion node (vessel onboard / shore-side server)
2. Network access from that machine to InfluxDB server (192.168.14.168:8086)
3. Decision on which topics to stream live vs continue recording to bags
4. For Approach 2: decision on MQTT broker deployment location

---

## References

- [InfluxDB Python Client — WriteAPI Deep Dive](https://www.influxdata.com/blog/influxdb-python-client-library-deep-dive-writeapi/)
- [InfluxDB v2 Write Optimization](https://docs.influxdata.com/influxdb/v2/write-data/best-practices/optimize-writes/)
- [InfluxDB Hardware Sizing Guidelines](https://docs.influxdata.com/influxdb/v1/guides/hardware_sizing/)
- [mqtt_client ROS2 Package (ika-rwth-aachen)](https://github.com/ika-rwth-aachen/mqtt_client)
- [Telegraf MQTT Consumer Plugin](https://docs.influxdata.com/telegraf/v1/input-plugins/mqtt_consumer/)
- [ros2_data_collection Framework](https://github.com/Minipada/ros2_data_collection)
- [diagnostic_remote_logging (ROS Package)](https://index.ros.org/p/diagnostic_remote_logging/)
- [Middleware Comparison for Distributed ROS2 Systems (arXiv)](https://arxiv.org/abs/2309.07496)
- [MQTT Broker Benchmarks 2023 (EMQX)](https://www.emqx.com/en/blog/open-mqtt-benchmarking-comparison-mqtt-brokers-in-2023)
