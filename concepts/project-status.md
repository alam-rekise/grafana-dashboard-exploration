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
  - Parallel processing — Pass 1 (16 workers for bag scanning) + Pass 2 (16 workers for sensor extraction)
  - Mode timeline matches `mission_time_analysis` ModeSegmentExtractor (boundary extension, gap filling, session splitting)
  - 16 measurements, 9.85M data points from 722 bag files (68 GB) in ~3.3 minutes
  - Every point tagged with active mode for flexible filtering
- **write.js**: Legacy CSV → InfluxDB pipeline (still works, used for pre-computed summary data)

### Infrastructure
- Docker Compose: InfluxDB 2.7 + Grafana 10.1.2
- Grafana provisioning: dashboards and datasources loaded from files
- Reusable panel templates in `panel-templates/`
- Concept documentation in `concepts/`
- Server deployment at 192.168.14.168

### Dashboard: Mission Mode Distribution (8 panels)
All provisioned, all aligned with `mission_time_analysis` output:
1. **Battery consumption rate** — %/hour drain per mode (bar chart, elapsed+difference+reduce, ns precision)
2. **Total battery drop %** — discharge per mode (bar chart, elapsed+difference, battery_state)
3. **Mode distribution** — time in each mode (pie chart, range(start:0), dthms unit, matches mission_time_analysis)
4. **Mode transitions with battery level** — colored mode backgrounds with battery % line + mode tooltip (battery_state, v.windowPeriod, fn: last)
5. **Temperature over time** — mode backgrounds with temperature line (v.windowPeriod, fn: last, auto-scale Y-axis)
6. **Humidity over time** — mode backgrounds with humidity line (v.windowPeriod, fn: last, auto-scale Y-axis)
7. **Heading comparison** — SBG Ellipse + AHRS8 on same chart (fn: last to avoid 0°/360° wrap-around, GNSS removed)
8. **Leak detection** — green dots (No Leak) + red dots (Leak Detected) with mode backgrounds (fn: max, v.windowPeriod)

### Key Decisions Made
- `/control_mode/feedback` is the correct mode source (not `/control_mode/status`)
- `elapsed+difference` with gap filtering for battery computations (not naive `difference()` which has cross-boundary contamination)
- `battery_state.percentage` to match mission_time_analysis (not battery_telemetry)
- `v.windowPeriod` + `fn: last` for adaptive resolution (not hardcoded intervals or fn: mean)
- `fn: max` for leak detection (catches brief leaks within aggregation windows)
- `range(start: 0)` for pie chart (mission_segments are summary data, not time-range-dependent)
- Mode timeline with boundary extension, gap filling, session splitting (matches ModeSegmentExtractor)
- Single combined Time Series panel for mode+battery (not separate panels)
- Mode tag on every data point (enables filtering any measurement by mode without joins)

## Roadmap: Prototype → MVP

### What MVP Needs

**More dashboards:**
- [ ] Navigation dashboard — vessel track on a map (lat/lon from GNSS), speed over time
- [ ] Power management dashboard — per-card power consumption from /pm/feedback
- [ ] Depth/altitude profile over time
- Remaining from mission_time_analysis: actuator_analysis, bms_analysis, computer_monitoring, imu_orientation_analysis, joystick_analysis, localization_quality, navigation_analysis, pid_analysis, rate_statistics, vessel_motion

**Usability:**
- [ ] CLI help text and error messages in extract-bag.py
- [ ] Clear instructions for processing a new mission end-to-end
- [ ] Handle edge cases gracefully (missing bags, corrupt files, partial missions)

**Data completeness:**
- [ ] Add dashboard panels for measurements not yet visualized (odometry, pack_status, etc.)
- [ ] Cross-mission comparison (overlay two missions on same chart)

**Tooltip & interactivity:**
- [ ] Fix mode info in tooltip (blocked by Grafana 10.1.2 bug — may require Grafana upgrade to 11.x)
- [ ] Drill-down links between dashboards

## Roadmap: MVP → Production

### Reliability
- [ ] Automated tests for extract-bag.py
- [ ] File tracking improvements (currently per-mission JSON)
- [ ] Structured logging
- [ ] Health checks for Docker containers

### Deployment
- [ ] Environment variables for configuration instead of hardcoded values
- [ ] Docker image for extract-bag.py
- [ ] CI/CD: auto-provision dashboards on deploy

### Scale
- [ ] Handle multiple vessels
- [ ] Data retention policies
- [ ] Performance optimization for large datasets

### Integration
- [ ] Live streaming: connect to ROS2 topics in real-time
- [ ] Webhook or API to trigger extraction when new bags are uploaded

## Known Limitations (Current Prototype)

| Limitation | Impact | Workaround |
|---|---|---|
| Grafana 10.1.2 tooltip.mode "all" breaks with stacked series | Mode name not shown in combined panel tooltip | Query C provides mode via value mappings |
| Battery rate ~0.01-0.02 difference vs mission_time_analysis | Minor precision difference in elapsed+difference pairing | Acceptable — matches to 2 decimal places |
| Mid-mission charging skews battery drop values | Direct mode shows negative drop (battery increased) | Filter by is_charging != true |
| extract-bag.py config is hardcoded | InfluxDB URL, token, org, bucket are in the script | Move to env vars for MVP |
| InfluxDB tag index caches deleted missions | Deleted mission names persist in dropdown until compaction | Restart InfluxDB or wait for auto-compaction |
