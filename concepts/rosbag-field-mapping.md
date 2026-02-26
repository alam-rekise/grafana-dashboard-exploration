# ROS Bag Field Mapping → Dashboard Requirements

## What We Need vs What's Available

### 1. Mode Distribution (which mode took how long)
**Topic:** /control_mode/feedback (~411 msgs across full dataset)
- Uses `current_mode_name` field (string: "Idle", "Navigation", "Direct", "Station", "Voyage")
- Only publishes on mode **change** (not continuously)
- Matches the `mission_time_analysis` package output used by Rekise for post-mission reports

**Note:** /control_mode/status (KeyValue[] array) was initially used but always reported "Idle" — it is NOT the correct mode source.

### 2. Mode Timeline with Battery Level
**Topics:**
- /control_mode/feedback → active mode at each timestamp (via `current_mode_name`)
- /telemetry/battery_state → charge_percentage: 0.855 (85.5%), voltage: 26.5V
- /pack_status → pack_state_of_charge: 85.5, pack_voltage: 26.5V
- Overlay battery % on top of mode timeline using a single combined Time Series panel (see `concepts/mode-timeline-panel.md`)

### 3. Power Consumption by Mode
**Topic:** /pm/feedback (3316 msgs)
- load_current: 0.0 (amps)
- bus_voltage: 26.51V
- temperature: 22.82
- header.frame_id: identifies which power card (e.g. "pm_altimeter(16)")

### 4. Total Battery Drop by Mode
**Topics:**
- /battery_state → percentage: 0.855, voltage: 26.5V, current: -3.7A
- /pack_status → pack_state_of_charge: 85.5, pack_depth_of_discharge: 14.0
- Correlate with /control_mode/status to know which mode was active

### 5. Battery Consumption Rate by Mode
- Same as above but calculate rate = battery_drop / duration_in_mode

### 6. Temperature Over Time
**Topic:** /temperature (238 msgs)
- temperature: 23.31
- Straightforward time series

### 7. Humidity Over Time
**Topic:** /humidity (238 msgs)
- relative_humidity: 32.32
- Straightforward time series

### 8. Heading Data Comparison
**Topics:**
- /imu/ellipse/sbg_ekf_euler → angle.z: 1.364 rad (yaw/heading from IMU)
- /telemetry/state → heading: 6.078 rad
- /moving_base_second/navheading → orientation quaternion (GPS heading)
- Plot all three on same time series for comparison

### 9. Leak Detection
**Topic:** /leak_detect (119 msgs)
- data: 0 (0 = no leak)
- Simple status over time

---

## InfluxDB Schema for ROS Bag Data

### Measurements and Fields

| Measurement | Tags | Fields | Source Topic |
|---|---|---|---|
| control_mode | mission, vessel, active_mode | (mode as tag) | /control_mode/status |
| battery | mission, vessel | voltage, percentage, current, charge | /battery_state |
| battery_telemetry | mission, vessel | voltage, charge_percentage, is_charging, error_code | /telemetry/battery_state |
| pack_status | mission, vessel | soc, voltage, current, dod, health, amphours | /pack_status |
| power_mgmt | mission, vessel, card_id | load_current, bus_voltage, temperature | /pm/feedback |
| temperature | mission, vessel | temperature | /temperature |
| humidity | mission, vessel | relative_humidity | /humidity |
| pressure | mission, vessel | fluid_pressure | /pressure |
| heading | mission, vessel | imu_yaw, telemetry_heading, gps_heading | combined from 3 topics |
| leak_detect | mission, vessel | status | /leak_detect |
| telemetry_state | mission, vessel | lat, lon, heading, depth, altitude, speed, course, yaw_rate | /telemetry/state |
| gnss | mission, vessel | latitude, longitude, altitude | /gnss/fix |

---

## Key Observations

1. /vessel/mode only has 1 message (value=0, STAGING) — not useful for mode tracking
2. /control_mode/feedback is the correct mode source — `current_mode_name` field, publishes on mode change only (~411 msgs across 722 files). /control_mode/status (KeyValue[] array) always reported "Idle" and is NOT reliable
3. Battery data available from 3 sources: /battery_state (standard), /telemetry/battery_state (Rekise), /pack_status (Orion BMS)
4. /pm/feedback has frame_id identifying which power card — useful as a tag
5. /telemetry/state has the richest vessel data: lat, lon, heading, speed, depth, altitude
6. Heading comparison needs quaternion-to-euler conversion for /moving_base_second/navheading
7. Full dataset: 722 .db3 files (~68 GB), 8.1M+ points, 14.7 hours mission duration
