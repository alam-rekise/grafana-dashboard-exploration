# Project Status & Roadmap

## Current Phase: Prototype

This project is in the **prototype** phase — building functional dashboards, iterating on queries and visualizations, and establishing the infrastructure for a complete mission analysis tool.

### Phase Definitions

| Phase | Goal | Key Question |
|---|---|---|
| **POC** (done) | Prove technical feasibility | "Can we read ROS bags directly into InfluxDB and visualize in Grafana?" |
| **Prototype** (current) | Build functional dashboards, iterate on layout and queries | "What should it look like? What data matters?" |
| **MVP** | Minimum usable version for the team | "Can someone else use this for a real mission without hand-holding?" |
| **Production** | Hardened, reliable, deployable | "Can this run unattended for every mission?" |

## POC (Completed)

- [x] Read ROS2 .db3 bag files with Python (rosbags library, no ROS2 install needed)
- [x] Register and deserialize custom Rekise message types (rkse_common_interfaces, rkse_telemetry_interfaces, etc.)
- [x] Write data points to InfluxDB from Python (influxdb-client)
- [x] Visualize time-series data in Grafana (basic pie chart from mission_segments)
- [x] Docker Compose setup for InfluxDB 2.7 + Grafana 10.1.2
- [x] Grafana provisioning — dashboards and datasources loaded from files on startup
- [x] Identify correct mode source: `/control_mode/feedback` (not `/control_mode/status` which always reported "Idle")
- [x] Tag every sensor point with the active mode at that timestamp (binary search on mode timeline)

## What's Been Built (Prototype)

### Data Pipeline
- **extract-bag.py**: Reads ROS2 .db3 bag files directly into InfluxDB
  - Two-pass approach: mode timeline first, then all sensor data
  - Parallel processing (8 workers, 68 GB in ~10 min)
  - 15 measurements, 8M+ data points from 722 bag files
  - Every point tagged with active mode for flexible filtering
- **write.js**: Legacy CSV → InfluxDB pipeline (still works, used for pre-computed summary data)

### Infrastructure
- Docker Compose: InfluxDB 2.7 + Grafana 10.1.2
- Grafana provisioning: dashboards and datasources loaded from files
- Reusable panel templates in `panel-templates/`
- Concept documentation in `concepts/`

### Dashboard: Mission Mode Distribution
5 panels, all provisioned:
1. **Battery consumption rate** — %/hour drain per mode (bar chart, join query)
2. **Total battery drop %** — discharge per mode (bar chart, difference query)
3. **Mode distribution** — time in each mode (pie chart)
4. **Mode transitions with battery level** — colored mode backgrounds with battery % line overlay (combined time series)
5. **Temperature over time** — colored mode backgrounds with temperature line overlay (same pattern as #4, right Y-axis 20-45°C)

### Key Decisions Made
- `/control_mode/feedback` is the correct mode source (not `/control_mode/status`)
- `difference()` approach for battery drop (not first-to-last which fails with interleaved modes)
- `join` approach for consumption rate (not inline reduce which had precision issues)
- Single combined Time Series panel for mode+battery (not separate panels)
- Mode tag on every data point (enables filtering any measurement by mode without joins)

## Roadmap: Prototype → MVP

### What MVP Needs

**Usability — someone else can run it:**
- [ ] CLI help text and error messages in extract-bag.py
- [ ] Clear instructions for processing a new mission end-to-end
- [ ] Handle edge cases gracefully (missing bags, corrupt files, partial missions)
- [ ] Input validation (does the bag directory exist? is InfluxDB reachable?)

**More dashboards:**
- [ ] Navigation dashboard — vessel track on a map (lat/lon from GNSS), speed over time
- [ ] Environmental dashboard — temperature, humidity, pressure over time
- [ ] Power management dashboard — per-card power consumption from /pm/feedback
- [ ] Heading comparison — IMU vs telemetry vs GPS heading on same chart
- [ ] Depth/altitude profile over time

**Data completeness:**
- [ ] Verify all 15 measurements render correctly in Grafana
- [ ] Add dashboard panels for measurements not yet visualized (odometry, navheading, pack_status, etc.)
- [ ] Cross-mission comparison (overlay two missions on same chart)

**Tooltip & interactivity:**
- [ ] Fix mode info in tooltip (blocked by Grafana 10.1.2 bug with tooltip.mode "all" on stacked series — may require Grafana upgrade to 11.x)
- [ ] Drill-down links between dashboards (click a mode in pie chart → filtered timeline)

## Roadmap: MVP → Production

### Reliability
- [ ] Automated tests for extract-bag.py (unit tests for mode lookup, field extraction)
- [ ] Idempotent re-processing (re-run same bags without duplicating data — already handled by InfluxDB upsert, but should be explicit)
- [ ] File tracking (skip already-processed bags, resume interrupted extractions)
- [ ] Error reporting and logging (structured logs, not just print statements)
- [ ] Health checks for Docker containers

### Deployment
- [ ] Single-command setup script (install deps, start Docker, configure InfluxDB, run extraction)
- [ ] Environment variables for configuration (InfluxDB URL, token, org, bucket) instead of hardcoded values
- [ ] Docker image for extract-bag.py (no Python dependency on host)
- [ ] CI/CD: auto-provision dashboards on deploy, validate JSON schemas

### Scale
- [ ] Handle multiple vessels (per-vessel dashboards, vessel selector variable)
- [ ] Handle multi-day missions (time range presets, mission metadata panel)
- [ ] Data retention policies (auto-delete old missions after N days, or archive to cold storage)
- [ ] Performance: optimize Flux queries for large datasets, consider continuous queries or tasks for pre-aggregation

### Team Features
- [ ] User roles in Grafana (viewer vs editor)
- [ ] Alerting (battery below threshold, leak detected, mode stuck in Idle too long)
- [ ] Mission notes/annotations (add comments to specific time ranges)
- [ ] Export dashboard as PDF report for post-mission review

### Integration
- [ ] Live streaming: connect to ROS2 topics in real-time (not just post-mission bags)
- [ ] Webhook or API to trigger extraction when new bags are uploaded
- [ ] Integration with Rekise's existing mission_time_analysis package

## Known Limitations (Current Prototype)

| Limitation | Impact | Workaround |
|---|---|---|
| Grafana 10.1.2 tooltip.mode "all" breaks with stacked series | Mode name not shown in combined panel tooltip | Mode visible as background color + legend |
| Pass 1 (mode timeline scan) is sequential | Can't parallelize across files because mode timeline must be complete before sensor processing | Acceptable — Pass 1 is fast (~7 min for 722 files) |
| Mid-mission charging skews battery drop values | Direct mode shows negative drop (battery increased) | Filter by is_charging != true, or analyze pre-charge period only |
| extract-bag.py config is hardcoded | InfluxDB URL, token, org, bucket are in the script | Move to env vars or CLI args for MVP |
| No automated tests | Can't verify extraction correctness without manual inspection | Add pytest suite for MVP |
