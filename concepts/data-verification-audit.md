# Data Verification Audit

**Date:** 2026-02-27
**Bucket:** vessel-data | **Org:** Rekise Marine
**Source:** 722 bag files (68 GB) | 2 missions | 32.49 hours of mission time

---

## Critical Findings

### 1. NAVHEADING IS CONSTANT AT 90.0°

All **418,016** navheading data points are exactly `90.0` degrees. Min = Max = Mean = 90.0 across every mode.

The GNSS heading sensor (`/moving_base_second/navheading`) was non-functional or uninitialized during the entire rosbag-20260223 mission. The line on the heading comparison panel is a flat line at 90° — it's not real heading data. Only ekf_euler and ahrs8 provide actual heading.

**Root cause to investigate:** The raw quaternion was likely `(0, 0, 0.7071, 0.7071)` — the identity-ish quaternion that produces exactly 90° through `atan2`. This suggests the u-blox GPS never achieved a valid heading fix.

### 2. MISSION-001 HAS NO SENSOR DATA

| Measurement | mission-001 | rosbag-20260223 |
|---|---|---|
| mission_segments | 199 segments | 305 segments |
| battery_telemetry | **0 points** | 86,387 |
| temperature | **0 points** | 178,601 |
| humidity | **0 points** | 178,601 |
| ekf_euler | **0 points** | 1,651,923 |
| ahrs8 | **0 points** | 1,727,818 |
| navheading | **0 points** | 418,016 |
| leak_detect | **0 points** | 84,616 |

mission-001 only has segment metadata (mode durations). All 7 sensor measurements exist **only** for rosbag-20260223. Any dashboard filtered to mission-001 will show empty sensor panels.

### 3. LEAK EVENTS ONLY IN DIRECT MODE

| Mode | Distinct status values |
|---|---|
| Direct | **0, 1** |
| Idle | 0 only |
| Navigation | 0 only |
| Station | 0 only |
| Voyage | 0 only |

Status `1` (Sensor A - Back) triggers exclusively during Direct mode. Either there's actual water ingress during surface operations, or thruster activation creates electrical noise that trips the sensor. This needs correlation with specific timestamps.

---

## Point Counts & Time Range

| Measurement | Field | Points | First | Last |
|---|---|---|---|---|
| mission_segments | duration_s | 504 | 2026-02-20 23:30:39Z | 2026-02-23 14:14:37Z |
| battery_telemetry | charge_percentage | 86,387 | 2026-02-22 23:30:20Z | 2026-02-23 23:30:16Z |
| temperature | temperature_c | 178,601 | 2026-02-22 23:30:20Z | 2026-02-23 23:30:17Z |
| humidity | relative_humidity | 178,601 | 2026-02-22 23:30:20Z | 2026-02-23 23:30:17Z |
| ekf_euler | heading_degrees | 1,651,923 | 2026-02-22 23:30:19Z | 2026-02-23 23:30:17Z |
| ahrs8 | heading_degrees | 1,727,818 | 2026-02-22 23:30:20Z | 2026-02-23 23:30:17Z |
| navheading | heading_degrees | 418,016 | 2026-02-22 23:30:20Z | 2026-02-23 23:30:17Z |
| leak_detect | status | 84,616 | 2026-02-22 23:30:20Z | 2026-02-23 23:30:17Z |

**Total: ~4.33M points**

All sensor data spans the same ~24hr window (Feb 22-23), confirming consistent extraction from the same bag file set.

## Sample Rates

| Sensor | Points | Observed Rate | Expected Rate |
|---|---|---|---|
| ahrs8 | 1,727,818 | ~20 Hz | 20 Hz |
| ekf_euler | 1,651,923 | ~19 Hz | 20 Hz |
| navheading | 418,016 | ~5 Hz | 5 Hz |
| temperature | 178,601 | ~2 Hz | 2 Hz |
| humidity | 178,601 | ~2 Hz | 2 Hz |
| battery_telemetry | 86,387 | ~1 Hz | 1 Hz |
| leak_detect | 84,616 | ~1 Hz | 1 Hz |

All match expected ROS topic publish rates.

## Value Distributions

| Measurement | Field | Min | Max | Mean |
|---|---|---|---|---|
| battery_telemetry | charge_percentage | 0.360 (36%) | 1.000 (100%) | 0.720 |
| temperature | temperature_c | 22.85°C | 42.00°C | 31.15°C |
| humidity | relative_humidity | 17.17% | 36.14% | 26.76% |
| ekf_euler | heading_degrees | 0.059° | 359.986° | 249.40° |
| ahrs8 | heading_degrees | 0.003° | 359.998° | 125.77° |
| navheading | heading_degrees | **90.0°** | **90.0°** | **90.0°** |

## Mode Distribution (points per mode)

| Mode | ekf_euler | ahrs8 | temp/humidity | battery | leak |
|---|---|---|---|---|---|
| **Direct** (43%) | 712,158 | 786,964 | 76,303 | 39,343 | 37,628 |
| **Idle** (25%) | 413,185 | 414,292 | 42,128 | 20,716 | 20,658 |
| **Navigation** (25%) | 416,758 | 416,739 | 47,084 | 20,836 | 20,836 |
| **Station** (5%) | 85,156 | 85,158 | 10,366 | 4,258 | 4,261 |
| **Voyage** (1.5%) | 24,666 | 24,665 | 2,720 | 1,234 | 1,233 |

Cross-measurement mode ratios are consistent — temperature/humidity identical, battery/leak nearly identical, ekf_euler/ahrs8 nearly identical. This confirms the mode-tagging pipeline is deterministic.

## Data Quality Checks

| Check | Result |
|---|---|
| Zero heading values (bad quaternion conversion) | **0** across all 3 heading measurements |
| Temperature/humidity co-sampling | **Confirmed** — identical counts per mode |
| Battery/leak co-sampling | **Confirmed** — within 1-3 points per mode |
| Heading full range coverage | ekf_euler and ahrs8 cover 0°-360°. navheading is **constant 90°** |
| Mission segment total duration | 32.49 hours (17.75h mission-001 + 14.74h rosbag-20260223) |

## Thermal Correlation with Mode

| Mode | Mean Temp (°C) | Mean Battery |
|---|---|---|
| Idle | 28.03 | 78.7% |
| Direct | 31.15 | 72.0% |
| Navigation | 33.30 | 58.8% |
| Station | 33.43 | 56.8% |
| Voyage | 34.98 | 61.7% |

Higher power modes show higher temperatures and lower battery — physically consistent with increased electronics thermal load and power draw.

## Mission Segments Breakdown

### Fields in mission_segments
- `duration_s` — segment duration in seconds
- `start_time_ns` — segment start time in nanoseconds
- `end_time_ns` — segment end time in nanoseconds
- `segment_number` — sequential segment index

### Total Duration by Mission

| Mission | Direct | Idle | Navigation | Station | Voyage | NO_BAG_RECORD | Total |
|---|---|---|---|---|---|---|---|
| mission-001 | 20,929.5s | 17,895.7s | 22,233.1s | 2,129.9s | 253.4s | 468.8s | **63,910.4s (17.75 hrs)** |
| rosbag-20260223 | 6,011.5s | 20,716.8s | 20,837.6s | 4,257.8s | 1,233.3s | — | **53,057.1s (14.74 hrs)** |

## Summary

**What's solid:** 4.33M points, sample rates match expected ROS topic rates, mode tagging is consistent across measurements, quaternion conversions are clean, thermal/power correlations are physically plausible.

**What needs attention:** navheading is dead data (constant 90°), mission-001 has no sensor telemetry, and leak events need timestamp-level investigation to determine if they're real or noise.
