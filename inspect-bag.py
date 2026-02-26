from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_typestore
from rosbags.typesys.msg import get_types_from_msg

typestore = get_typestore(Stores.ROS2_HUMBLE)

bag_path = "/home/alam/post-mission-analysis/20260223_050019_0.db3"

# Register custom message types from .msg definitions
# get_types_from_msg parses the .msg text into the format typestore.register expects
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

# Parse and register all custom types
all_types = {}
for msgtype, msgdef in custom_msg_defs:
    all_types.update(get_types_from_msg(msgdef, msgtype))

typestore.register(all_types)

# ====================================================================
# Key topics to inspect
# ====================================================================
key_topics = [
    # Standard ROS2 types
    "/battery_state",
    "/temperature",
    "/humidity",
    "/pressure",
    "/odometry/filtered",
    "/moving_base_second/navheading",
    "/gnss/fix",
    # Custom Rekise types (now registered)
    "/vessel/mode",
    "/control_mode/status",
    "/telemetry/state",
    "/telemetry/battery_state",
    "/pack_status",
    "/pm/feedback",
    "/leak_detect",
    "/imu/ellipse/sbg_ekf_euler",
]

def print_fields(msg, prefix="", depth=0):
    """Recursively print all fields of a ROS message"""
    if depth > 3:
        print(f"    {prefix}: (nested too deep, skipping)")
        return

    for field_name in msg.__dataclass_fields__:
        value = getattr(msg, field_name)
        full_name = f"{prefix}{field_name}" if not prefix else f"{prefix}.{field_name}"

        if hasattr(value, '__dataclass_fields__'):
            print(f"    {full_name}: (nested)")
            print_fields(value, prefix=f"    {full_name}", depth=depth+1)
        else:
            val_str = str(value)
            if len(val_str) > 80:
                val_str = val_str[:80] + "..."
            print(f"    {full_name}: {val_str}")

with Reader(bag_path) as reader:
    print("=== Inspecting Key Topics — First Message Fields ===\n")

    for topic_name in key_topics:
        if topic_name not in reader.topics:
            print(f"TOPIC: {topic_name}")
            print(f"  NOT FOUND in this bag\n")
            continue

        info = reader.topics[topic_name]
        print(f"TOPIC: {topic_name}")
        print(f"  Type: {info.msgtype}")
        print(f"  Count: {info.msgcount}")

        for connection, timestamp, rawdata in reader.messages():
            if connection.topic == topic_name:
                try:
                    msg = typestore.deserialize_cdr(rawdata, connection.msgtype)
                    print(f"  Fields (from first message):")
                    print_fields(msg, prefix="")
                    print(f"  Timestamp: {timestamp} ns")
                except Exception as e:
                    print(f"  *** ERROR: {e} ***")
                break

        print()
