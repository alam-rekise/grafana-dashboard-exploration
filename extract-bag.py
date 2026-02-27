import sys
import os
import glob
import argparse
import math
import bisect
import time
import re
import json
import hashlib
from multiprocessing import Pool, cpu_count

from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_typestore
from rosbags.typesys.msg import get_types_from_msg
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

# ====================================================================
# InfluxDB Configuration
# ====================================================================
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "XZvi_7cfAtdoSsmdG_-1enydzbGSlTYSqmEgB2XAuwxRqpzXbeP_ThABKMyLPfCmOr1rueEXQde_wthNJwz1tw=="
INFLUX_ORG = "Rekise Marine"
INFLUX_BUCKET = "vessel-data"

BATCH_SIZE = 5000

# ====================================================================
# Custom ROS2 Message Type Registration
# ====================================================================
typestore = get_typestore(Stores.ROS2_HUMBLE)

custom_msg_defs = [
    ("rkse_common_interfaces/msg/KeyValue", "string key\nstring value"),

    ("rkse_common_interfaces/msg/VesselMode",
     "uint8 VESSEL_MODE_STAGING=0\n"
     "uint8 VESSEL_MODE_ACTIVE=1\n"
     "std_msgs/Header header\n"
     "uint8 value"),

    ("rkse_common_interfaces/msg/ControlModeStatus",
     "std_msgs/Header header\n"
     "rkse_common_interfaces/KeyValue[] data"),

    ("rkse_common_interfaces/msg/ControlModeFeedback",
     "std_msgs/Header header\n"
     "string manual_preset_name\n"
     "string stationary_preset_name\n"
     "string current_mode_name\n"
     "uint8 current_mode\n"
     "builtin_interfaces/Duration duration"),

    ("rkse_common_interfaces/msg/LeakStatus",
     "std_msgs/Header header\n"
     "uint8 data"),

    ("rkse_telemetry_interfaces/msg/BatteryStateTelemetry",
     "uint8 NO_ERROR=0\n"
     "uint8 LOW_BATTERY=1\n"
     "uint8 ERROR=2\n"
     "builtin_interfaces/Time stamp\n"
     "float32 voltage\n"
     "float32 charge_percentage\n"
     "bool is_charging\n"
     "uint8 error_code\n"
     "string message"),

    ("rkse_telemetry_interfaces/msg/StateTelemetry",
     "builtin_interfaces/Time stamp\n"
     "float64 latitude\n"
     "float64 longitude\n"
     "float32 heading\n"
     "float32 vertical_speed\n"
     "float32 depth\n"
     "float32 altitude\n"
     "float32 course_over_ground\n"
     "float32 speed_over_ground\n"
     "float32 yaw_rate"),

    ("rkse_orion_interfaces/msg/PackStatus",
     "builtin_interfaces/Time stamp\n"
     "bool charge_power_status\n"
     "bool ready_power_status\n"
     "bool multipurpose_input\n"
     "bool bms_errors_present\n"
     "bool charger_safety\n"
     "bool charge_enable\n"
     "bool discharge_enable\n"
     "float32 pack_state_of_charge\n"
     "float32 pack_charge_current_limit\n"
     "float32 pack_discharge_current_limit\n"
     "float32 pack_current\n"
     "float32 pack_voltage\n"
     "float32 pack_amphours\n"
     "float32 pack_depth_of_discharge\n"
     "float32 pack_health\n"
     "float32 pack_summed_voltage\n"
     "float32 total_pack_cycles"),

    ("rkse_driver_interfaces/msg/PowerManagementFeedback",
     "std_msgs/Header header\n"
     "bool load_on_off\n"
     "bool adc_on_off\n"
     "bool card_limit_tripped\n"
     "float32 load_current\n"
     "float32 bus_voltage\n"
     "float32 temperature\n"
     "float32 control_current\n"
     "float32 averaged_time\n"
     "float32 value_tripped\n"
     "float32 startup_current\n"
     "bool switch_on_off\n"
     "bool watchdog_status\n"
     "bool reboot\n"
     "bool power_mode_on_off\n"
     "bool power_mode_status\n"
     "bool curr_max\n"
     "bool curr_max_warn\n"
     "bool volt_max\n"
     "bool volt_max_warn\n"
     "bool volt_min_warn\n"
     "bool volt_min\n"
     "bool temp_card_max\n"
     "bool temp_card_max_warn"),

    ("sbg_driver/msg/SbgEkfStatus",
     "uint8 solution_mode\n"
     "bool attitude_valid\n"
     "bool heading_valid\n"
     "bool velocity_valid\n"
     "bool position_valid\n"
     "bool vert_ref_used\n"
     "bool mag_ref_used\n"
     "bool gps1_vel_used\n"
     "bool gps1_pos_used\n"
     "bool gps1_course_used\n"
     "bool gps1_hdt_used\n"
     "bool gps2_vel_used\n"
     "bool gps2_pos_used\n"
     "bool gps2_course_used\n"
     "bool gps2_hdt_used\n"
     "bool odo_used"),

    ("sbg_driver/msg/SbgEkfEuler",
     "std_msgs/Header header\n"
     "uint32 time_stamp\n"
     "geometry_msgs/Vector3 angle\n"
     "geometry_msgs/Vector3 accuracy\n"
     "sbg_driver/SbgEkfStatus status"),
]

all_types = {}
for msgtype, msgdef in custom_msg_defs:
    all_types.update(get_types_from_msg(msgdef, msgtype))
typestore.register(all_types)


# ====================================================================
# Mode Timeline — Pass 1
# ====================================================================
class ModeTimeline:
    def __init__(self, segments):
        self.segments = segments
        self.start_times = [seg["start_time"] for seg in segments]

    def lookup(self, timestamp_ns):
        if not self.segments:
            return "UNKNOWN"

        idx = bisect.bisect_right(self.start_times, timestamp_ns) - 1

        if idx < 0:
            return self.segments[0]["mode"]

        return self.segments[idx]["mode"]


def build_mode_timeline(bag_files):
    print("=== Pass 1: Building mode timeline ===")
    print(f"  Scanning {len(bag_files)} bag files for /control_mode/feedback...")

    mode_events = []

    for i, bag_path in enumerate(bag_files):
        with Reader(bag_path) as reader:
            if "/control_mode/feedback" not in reader.topics:
                if (i + 1) % 100 == 0:
                    print(f"    Scanned {i + 1}/{len(bag_files)} files...")
                continue
            for connection, timestamp, rawdata in reader.messages():
                if connection.topic == "/control_mode/feedback":
                    msg = typestore.deserialize_cdr(rawdata, connection.msgtype)
                    mode_name = msg.current_mode_name or "UNKNOWN"
                    mode_events.append((timestamp, mode_name))
        if (i + 1) % 100 == 0 or i == len(bag_files) - 1:
            print(f"    Scanned {i + 1}/{len(bag_files)} files...")

    mode_events.sort(key=lambda x: x[0])
    print(f"  Read {len(mode_events)} feedback messages")

    if not mode_events:
        print("  WARNING: No /control_mode/feedback messages found!")
        return ModeTimeline([])

    # Build segments — new segment only when mode changes
    segments = []
    for ts, mode in mode_events:
        if not segments or mode != segments[-1]["mode"]:
            if segments:
                segments[-1]["end_time"] = ts
            segments.append({
                "mode": mode,
                "start_time": ts,
                "end_time": None,
                "segment_number": len(segments) + 1,
            })

    # Close last segment with last event timestamp
    segments[-1]["end_time"] = mode_events[-1][0]

    # Calculate durations
    for seg in segments:
        seg["duration_ns"] = seg["end_time"] - seg["start_time"]
        seg["duration_s"] = seg["duration_ns"] / 1e9

    # Print summary
    mode_counts = {}
    for seg in segments:
        mode_counts[seg["mode"]] = mode_counts.get(seg["mode"], 0) + 1

    print(f"  Found {len(segments)} mode segments:")
    for mode, count in sorted(mode_counts.items()):
        print(f"    {mode}: {count} segments")

    return ModeTimeline(segments)


# ====================================================================
# Helpers
# ====================================================================
def quaternion_to_heading_degrees(x, y, z, w):
    """Convert quaternion orientation to heading in degrees (0-360)."""
    yaw_rad = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    heading_deg = math.degrees(yaw_rad)
    if heading_deg < 0:
        heading_deg += 360.0
    return heading_deg


# ====================================================================
# Topic Processors — one per topic, returns (fields_dict, extra_tags_dict)
# ====================================================================
def process_battery_state(msg):
    fields = {
        "voltage": float(msg.voltage),
        "current": float(msg.current),
        "charge": float(msg.charge),
        "capacity": float(msg.capacity),
        "percentage": float(msg.percentage),
        "temperature": float(msg.temperature),
        "power_supply_status": int(msg.power_supply_status),
        "power_supply_health": int(msg.power_supply_health),
        "present": bool(msg.present),
    }
    return fields, {}


def process_temperature(msg):
    return {"temperature_c": float(msg.temperature)}, {}


def process_humidity(msg):
    return {"relative_humidity": float(msg.relative_humidity)}, {}


def process_pressure(msg):
    return {"fluid_pressure": float(msg.fluid_pressure)}, {}


def process_odometry(msg):
    fields = {
        "position_x": float(msg.pose.pose.position.x),
        "position_y": float(msg.pose.pose.position.y),
        "position_z": float(msg.pose.pose.position.z),
        "orientation_x": float(msg.pose.pose.orientation.x),
        "orientation_y": float(msg.pose.pose.orientation.y),
        "orientation_z": float(msg.pose.pose.orientation.z),
        "orientation_w": float(msg.pose.pose.orientation.w),
        "linear_velocity_x": float(msg.twist.twist.linear.x),
        "linear_velocity_y": float(msg.twist.twist.linear.y),
        "linear_velocity_z": float(msg.twist.twist.linear.z),
        "angular_velocity_x": float(msg.twist.twist.angular.x),
        "angular_velocity_y": float(msg.twist.twist.angular.y),
        "angular_velocity_z": float(msg.twist.twist.angular.z),
    }
    return fields, {}


def process_navheading(msg):
    x, y, z, w = float(msg.orientation.x), float(msg.orientation.y), float(msg.orientation.z), float(msg.orientation.w)
    fields = {
        "orientation_x": x,
        "orientation_y": y,
        "orientation_z": z,
        "orientation_w": w,
        "angular_velocity_x": float(msg.angular_velocity.x),
        "angular_velocity_y": float(msg.angular_velocity.y),
        "angular_velocity_z": float(msg.angular_velocity.z),
        "heading_degrees": quaternion_to_heading_degrees(x, y, z, w),
    }
    return fields, {}


def process_gnss(msg):
    fields = {
        "latitude": float(msg.latitude),
        "longitude": float(msg.longitude),
        "altitude": float(msg.altitude),
        "status": int(msg.status.status),
        "service": int(msg.status.service),
    }
    return fields, {}


def process_vessel_mode(msg):
    return {"value": int(msg.value)}, {}


def process_telemetry_state(msg):
    fields = {
        "latitude": float(msg.latitude),
        "longitude": float(msg.longitude),
        "heading": float(msg.heading),
        "vertical_speed": float(msg.vertical_speed),
        "depth": float(msg.depth),
        "altitude": float(msg.altitude),
        "course_over_ground": float(msg.course_over_ground),
        "speed_over_ground": float(msg.speed_over_ground),
        "yaw_rate": float(msg.yaw_rate),
    }
    return fields, {}


def process_battery_telemetry(msg):
    fields = {
        "voltage": float(msg.voltage),
        "charge_percentage": float(msg.charge_percentage),
        "is_charging": bool(msg.is_charging),
        "error_code": int(msg.error_code),
    }
    return fields, {}


def process_pack_status(msg):
    fields = {
        "charge_power_status": bool(msg.charge_power_status),
        "ready_power_status": bool(msg.ready_power_status),
        "multipurpose_input": bool(msg.multipurpose_input),
        "bms_errors_present": bool(msg.bms_errors_present),
        "charger_safety": bool(msg.charger_safety),
        "charge_enable": bool(msg.charge_enable),
        "discharge_enable": bool(msg.discharge_enable),
        "pack_state_of_charge": float(msg.pack_state_of_charge),
        "pack_charge_current_limit": float(msg.pack_charge_current_limit),
        "pack_discharge_current_limit": float(msg.pack_discharge_current_limit),
        "pack_current": float(msg.pack_current),
        "pack_voltage": float(msg.pack_voltage),
        "pack_amphours": float(msg.pack_amphours),
        "pack_depth_of_discharge": float(msg.pack_depth_of_discharge),
        "pack_health": float(msg.pack_health),
        "pack_summed_voltage": float(msg.pack_summed_voltage),
        "total_pack_cycles": float(msg.total_pack_cycles),
    }
    return fields, {}


def process_power_mgmt(msg):
    fields = {
        "load_on_off": bool(msg.load_on_off),
        "adc_on_off": bool(msg.adc_on_off),
        "card_limit_tripped": bool(msg.card_limit_tripped),
        "load_current": float(msg.load_current),
        "bus_voltage": float(msg.bus_voltage),
        "temperature": float(msg.temperature),
        "control_current": float(msg.control_current),
        "averaged_time": float(msg.averaged_time),
        "value_tripped": float(msg.value_tripped),
        "startup_current": float(msg.startup_current),
        "switch_on_off": bool(msg.switch_on_off),
        "watchdog_status": bool(msg.watchdog_status),
        "reboot": bool(msg.reboot),
        "power_mode_on_off": bool(msg.power_mode_on_off),
        "power_mode_status": bool(msg.power_mode_status),
        "curr_max": bool(msg.curr_max),
        "curr_max_warn": bool(msg.curr_max_warn),
        "volt_max": bool(msg.volt_max),
        "volt_max_warn": bool(msg.volt_max_warn),
        "volt_min_warn": bool(msg.volt_min_warn),
        "volt_min": bool(msg.volt_min),
        "temp_card_max": bool(msg.temp_card_max),
        "temp_card_max_warn": bool(msg.temp_card_max_warn),
    }
    extra_tags = {}
    if hasattr(msg, 'header') and hasattr(msg.header, 'frame_id') and msg.header.frame_id:
        extra_tags["card_id"] = msg.header.frame_id
    return fields, extra_tags


def process_ahrs8(msg):
    x, y, z, w = float(msg.orientation.x), float(msg.orientation.y), float(msg.orientation.z), float(msg.orientation.w)
    fields = {
        "orientation_x": x,
        "orientation_y": y,
        "orientation_z": z,
        "orientation_w": w,
        "angular_velocity_x": float(msg.angular_velocity.x),
        "angular_velocity_y": float(msg.angular_velocity.y),
        "angular_velocity_z": float(msg.angular_velocity.z),
        "heading_degrees": quaternion_to_heading_degrees(x, y, z, w),
    }
    return fields, {}


def process_leak_detect(msg):
    return {"status": int(msg.data)}, {}


def process_ekf_euler(msg):
    yaw_rad = float(msg.angle.z)
    heading_deg = math.degrees(yaw_rad)
    if heading_deg < 0:
        heading_deg += 360.0
    fields = {
        "roll": float(msg.angle.x),
        "pitch": float(msg.angle.y),
        "yaw": yaw_rad,
        "heading_degrees": heading_deg,
        "accuracy_roll": float(msg.accuracy.x),
        "accuracy_pitch": float(msg.accuracy.y),
        "accuracy_yaw": float(msg.accuracy.z),
        "time_stamp": int(msg.time_stamp),
        "solution_mode": int(msg.status.solution_mode),
        "attitude_valid": bool(msg.status.attitude_valid),
        "heading_valid": bool(msg.status.heading_valid),
        "velocity_valid": bool(msg.status.velocity_valid),
        "position_valid": bool(msg.status.position_valid),
        "vert_ref_used": bool(msg.status.vert_ref_used),
        "mag_ref_used": bool(msg.status.mag_ref_used),
        "gps1_vel_used": bool(msg.status.gps1_vel_used),
        "gps1_pos_used": bool(msg.status.gps1_pos_used),
        "gps1_course_used": bool(msg.status.gps1_course_used),
        "gps1_hdt_used": bool(msg.status.gps1_hdt_used),
        "gps2_vel_used": bool(msg.status.gps2_vel_used),
        "gps2_pos_used": bool(msg.status.gps2_pos_used),
        "gps2_course_used": bool(msg.status.gps2_course_used),
        "gps2_hdt_used": bool(msg.status.gps2_hdt_used),
        "odo_used": bool(msg.status.odo_used),
    }
    return fields, {}


# ====================================================================
# Topic → (measurement_name, processor_function)
# ====================================================================
TOPIC_PROCESSORS = {
    "/battery_state":                 ("battery_state",     process_battery_state),
    "/temperature":                   ("temperature",       process_temperature),
    "/humidity":                      ("humidity",          process_humidity),
    "/pressure":                      ("pressure",          process_pressure),
    "/odometry/filtered":             ("odometry",          process_odometry),
    "/moving_base_second/navheading": ("navheading",        process_navheading),
    "/gnss/fix":                      ("gnss",              process_gnss),
    "/vessel/mode":                   ("vessel_mode",       process_vessel_mode),
    "/telemetry/state":               ("telemetry_state",   process_telemetry_state),
    "/telemetry/battery_state":       ("battery_telemetry", process_battery_telemetry),
    "/pack_status":                   ("pack_status",       process_pack_status),
    "/pm/feedback":                   ("power_mgmt",        process_power_mgmt),
    "/leak_detect":                   ("leak_detect",       process_leak_detect),
    "/imu/ellipse/sbg_ekf_euler":     ("ekf_euler",         process_ekf_euler),
    "/imu/ahrs8/data":                ("ahrs8",             process_ahrs8),
}


# ====================================================================
# Helper: create an InfluxDB Point from processed fields
# ====================================================================
def create_point(measurement, timestamp, fields, tags, extra_tags):
    point = Point(measurement)

    for tag_name, tag_value in tags.items():
        point.tag(tag_name, tag_value)
    for tag_name, tag_value in extra_tags.items():
        point.tag(tag_name, str(tag_value))

    for field_name, value in fields.items():
        if isinstance(value, bool):
            point.field(field_name, value)
        elif isinstance(value, int):
            point.field(field_name, value)
        elif isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                continue
            point.field(field_name, value)
        else:
            point.field(field_name, str(value))

    point.time(timestamp, WritePrecision.NS)
    return point


# ====================================================================
# Worker function for parallel Pass 2
# ====================================================================
def process_single_bag(args_tuple):
    """Process one .db3 file — runs in a worker process."""
    bag_path, mission, vessel, segments_data, dry_run = args_tuple

    # Each worker needs its own typestore
    worker_typestore = get_typestore(Stores.ROS2_HUMBLE)
    worker_types = {}
    for msgtype, msgdef in custom_msg_defs:
        worker_types.update(get_types_from_msg(msgdef, msgtype))
    worker_typestore.register(worker_types)

    # Each worker needs its own mode timeline
    mode_timeline = ModeTimeline(segments_data)

    # Each worker needs its own InfluxDB connection
    write_api = None
    client = None
    if not dry_run:
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        write_api = client.write_api(write_options=SYNCHRONOUS)

    base_tags = {"mission": mission, "vessel": vessel}
    file_points = {topic: [] for topic in TOPIC_PROCESSORS}
    topic_counts = {}
    topic_errors = {}
    file_msg_count = 0
    file_start = time.time()

    with Reader(bag_path) as reader:
        for connection, timestamp, rawdata in reader.messages():
            topic = connection.topic
            if topic not in TOPIC_PROCESSORS:
                continue

            measurement_name, processor_fn = TOPIC_PROCESSORS[topic]

            try:
                msg = worker_typestore.deserialize_cdr(rawdata, connection.msgtype)
                fields, extra_tags = processor_fn(msg)

                mode = mode_timeline.lookup(timestamp)
                tags = {**base_tags, "mode": mode}

                point = create_point(measurement_name, timestamp, fields, tags, extra_tags)
                file_points[topic].append(point)
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
                file_msg_count += 1

                if write_api and len(file_points[topic]) >= BATCH_SIZE:
                    write_api.write(bucket=INFLUX_BUCKET, record=file_points[topic], write_precision=WritePrecision.NS)
                    file_points[topic] = []

            except Exception as e:
                topic_errors[topic] = topic_errors.get(topic, 0) + 1

    # Write remaining points
    for topic, points in file_points.items():
        if points and write_api:
            write_api.write(bucket=INFLUX_BUCKET, record=points, write_precision=WritePrecision.NS)

    if client:
        client.close()

    file_elapsed = time.time() - file_start
    return (os.path.basename(bag_path), file_msg_count, topic_counts, topic_errors, file_elapsed)


# ====================================================================
# Tracking: skip already-processed files
# ====================================================================
TRACKER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracking")


def file_fingerprint(path):
    """Generate a fingerprint from filename + size + mtime (fast, no hashing)."""
    stat = os.stat(path)
    return f"{os.path.basename(path)}:{stat.st_size}:{int(stat.st_mtime)}"


def load_tracker(mission):
    os.makedirs(TRACKER_DIR, exist_ok=True)
    tracker_path = os.path.join(TRACKER_DIR, f"{mission}.json")
    if os.path.exists(tracker_path):
        with open(tracker_path, "r") as f:
            return json.load(f)
    return {"mission": mission, "processed_files": {}}


def save_tracker(mission, tracker):
    tracker_path = os.path.join(TRACKER_DIR, f"{mission}.json")
    with open(tracker_path, "w") as f:
        json.dump(tracker, f, indent=2)


def filter_new_files(bag_files, tracker):
    processed = tracker.get("processed_files", {})
    new_files = []
    skipped = 0
    for path in bag_files:
        fp = file_fingerprint(path)
        if os.path.basename(path) in processed and processed[os.path.basename(path)] == fp:
            skipped += 1
        else:
            new_files.append(path)
    return new_files, skipped


# ====================================================================
# Main
# ====================================================================
def natural_sort_key(path):
    """Sort file paths naturally: _0, _1, _2, ... _10, _11 (not _0, _1, _10, _11, _2)"""
    name = os.path.basename(path)
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', name)]


def main():
    parser = argparse.ArgumentParser(description="Extract ROS2 bag data → InfluxDB")
    parser.add_argument("--mission", required=True, help="Mission name (e.g. rosbag-20260223)")
    bag_group = parser.add_mutually_exclusive_group(required=True)
    bag_group.add_argument("--bag", help="Path to a single .db3 bag file")
    bag_group.add_argument("--bag-dir", help="Path to directory containing .db3 files")
    parser.add_argument("--vessel", default="AUV_01", help="Vessel name (default: AUV_01)")
    parser.add_argument("--dry-run", action="store_true", help="Process without writing to InfluxDB")
    parser.add_argument("--force", action="store_true", help="Re-process all files, ignore tracking")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel workers for Pass 2 (default: 1)")
    args = parser.parse_args()

    start_time = time.time()

    # Resolve bag file list
    if args.bag_dir:
        all_bag_files = sorted(glob.glob(os.path.join(args.bag_dir, "*.db3")), key=natural_sort_key)
        if not all_bag_files:
            print(f"ERROR: No .db3 files found in {args.bag_dir}")
            sys.exit(1)
    else:
        all_bag_files = [args.bag]

    # Filter already-processed files
    tracker = load_tracker(args.mission)
    if args.force:
        bag_files = all_bag_files
        skipped = 0
    else:
        bag_files, skipped = filter_new_files(all_bag_files, tracker)

    if not bag_files:
        print(f"All {len(all_bag_files)} files already processed for mission '{args.mission}'.")
        print(f"Use --force to re-process everything.")
        return

    total_size_mb = sum(os.path.getsize(f) for f in bag_files) / (1024 * 1024)

    # --- Setup ---
    print("=== Setup ===")
    print(f"  Mission:  {args.mission}")
    print(f"  Bag files: {len(bag_files)} new ({total_size_mb:.0f} MB)")
    if skipped > 0:
        print(f"  Skipped:  {skipped} already processed")
    if len(bag_files) > 1:
        print(f"    First: {os.path.basename(bag_files[0])}")
        print(f"    Last:  {os.path.basename(bag_files[-1])}")
    else:
        print(f"    File: {bag_files[0]}")
    print(f"  Vessel:   {args.vessel}")
    print(f"  Dry run:  {args.dry_run}")
    print(f"  InfluxDB: {INFLUX_URL} → {INFLUX_BUCKET}")
    print()

    # Connect to InfluxDB
    write_api = None
    client = None
    if not args.dry_run:
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        write_api = client.write_api(write_options=SYNCHRONOUS)
        print("  Connected to InfluxDB")
    else:
        print("  Dry run — skipping InfluxDB connection")
    print()

    base_tags = {"mission": args.mission, "vessel": args.vessel}

    # --- Pass 1: Build mode timeline across ALL bag files (including already processed) ---
    mode_timeline = build_mode_timeline(all_bag_files)
    segments = mode_timeline.segments

    # Write mission segments
    if segments:
        segment_points = []
        for seg in segments:
            tags = {**base_tags, "mode": seg["mode"]}
            fields = {
                "segment_number": seg["segment_number"],
                "duration_s": seg["duration_s"],
                "start_time_ns": seg["start_time"],
                "end_time_ns": seg["end_time"],
            }
            segment_points.append(
                create_point("mission_segments", seg["start_time"], fields, tags, {})
            )

        print(f"\n  Writing {len(segment_points)} points to 'mission_segments'...")
        if write_api:
            write_api.write(bucket=INFLUX_BUCKET, record=segment_points, write_precision=WritePrecision.NS)
        print("  Done.")
    print()

    # --- Pass 2: Process all sensor topics across ALL bag files ---
    num_workers = min(args.workers, len(bag_files))
    print(f"=== Pass 2: Processing sensor topics ({num_workers} workers) ===")

    # Prepare worker arguments — segments as plain dicts (picklable)
    worker_args = [
        (bag_path, args.mission, args.vessel, segments, args.dry_run)
        for bag_path in bag_files
    ]

    topic_counts = {topic: 0 for topic in TOPIC_PROCESSORS}
    topic_errors = {topic: 0 for topic in TOPIC_PROCESSORS}
    total_written = len(segments) if segments else 0
    completed = 0

    if num_workers > 1:
        # Parallel processing
        with Pool(processes=num_workers) as pool:
            for result in pool.imap_unordered(process_single_bag, worker_args):
                filename, msg_count, counts, errors, file_elapsed = result
                completed += 1
                total_written += msg_count

                for topic, cnt in counts.items():
                    topic_counts[topic] = topic_counts.get(topic, 0) + cnt
                for topic, cnt in errors.items():
                    topic_errors[topic] = topic_errors.get(topic, 0) + cnt

                # Mark file as processed
                if not args.dry_run:
                    full_path = os.path.join(args.bag_dir or os.path.dirname(args.bag), filename)
                    if os.path.exists(full_path):
                        tracker["processed_files"][filename] = file_fingerprint(full_path)
                        save_tracker(args.mission, tracker)

                pct = completed / len(bag_files) * 100
                elapsed_total = time.time() - start_time
                print(f"  [{completed}/{len(bag_files)}] {filename}: "
                      f"{msg_count} points ({file_elapsed:.1f}s) — "
                      f"{pct:.0f}% done, elapsed {elapsed_total:.0f}s")
    else:
        # Sequential processing (workers=1)
        for worker_arg in worker_args:
            result = process_single_bag(worker_arg)
            filename, msg_count, counts, errors, file_elapsed = result
            completed += 1
            total_written += msg_count

            for topic, cnt in counts.items():
                topic_counts[topic] = topic_counts.get(topic, 0) + cnt
            for topic, cnt in errors.items():
                topic_errors[topic] = topic_errors.get(topic, 0) + cnt

            # Mark file as processed
            if not args.dry_run:
                full_path = os.path.join(args.bag_dir or os.path.dirname(args.bag), filename)
                if os.path.exists(full_path):
                    tracker["processed_files"][filename] = file_fingerprint(full_path)
                    save_tracker(args.mission, tracker)

            pct = completed / len(bag_files) * 100
            elapsed_total = time.time() - start_time
            print(f"  [{completed}/{len(bag_files)}] {filename}: "
                  f"{msg_count} points ({file_elapsed:.1f}s) — "
                  f"{pct:.0f}% done, elapsed {elapsed_total:.0f}s")

    # --- Summary ---
    elapsed = time.time() - start_time
    print(f"\n=== Summary ===")
    print(f"  Bag files processed: {len(bag_files)}")
    print(f"  Workers: {num_workers}")
    print(f"  Total points: {total_written}")
    if segments:
        print(f"    mission_segments: {len(segments)}")
    for topic in TOPIC_PROCESSORS:
        if topic_counts.get(topic, 0) > 0:
            measurement_name = TOPIC_PROCESSORS[topic][0]
            err_str = f" ({topic_errors.get(topic, 0)} errors)" if topic_errors.get(topic, 0) > 0 else ""
            print(f"    {measurement_name}: {topic_counts[topic]}{err_str}")
    print(f"  Elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")

    if client:
        client.close()

    print("Done!")


if __name__ == "__main__":
    main()
