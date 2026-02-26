import sys
from datetime import datetime
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_typestore
from rosbags.typesys.msg import get_types_from_msg

typestore = get_typestore(Stores.ROS2_HUMBLE)

custom_msg_defs = [
    ("rkse_common_interfaces/msg/KeyValue", "string key\nstring value"),
    ("rkse_common_interfaces/msg/VesselMode",
     "uint8 VESSEL_MODE_STAGING=0\nuint8 VESSEL_MODE_ACTIVE=1\nstd_msgs/Header header\nuint8 value"),
    ("rkse_common_interfaces/msg/ControlModeStatus",
     "std_msgs/Header header\nrkse_common_interfaces/KeyValue[] data"),
    ("rkse_common_interfaces/msg/LeakStatus",
     "std_msgs/Header header\nuint8 data"),
    ("rkse_telemetry_interfaces/msg/BatteryStateTelemetry",
     "uint8 NO_ERROR=0\nuint8 LOW_BATTERY=1\nuint8 ERROR=2\nbuiltin_interfaces/Time stamp\n"
     "float32 voltage\nfloat32 charge_percentage\nbool is_charging\nuint8 error_code\nstring message"),
    ("rkse_telemetry_interfaces/msg/StateTelemetry",
     "builtin_interfaces/Time stamp\nfloat64 latitude\nfloat64 longitude\nfloat32 heading\n"
     "float32 vertical_speed\nfloat32 depth\nfloat32 altitude\nfloat32 course_over_ground\n"
     "float32 speed_over_ground\nfloat32 yaw_rate"),
    ("rkse_orion_interfaces/msg/PackStatus",
     "builtin_interfaces/Time stamp\nbool charge_power_status\nbool ready_power_status\n"
     "bool multipurpose_input\nbool bms_errors_present\nbool charger_safety\nbool charge_enable\n"
     "bool discharge_enable\nfloat32 pack_state_of_charge\nfloat32 pack_charge_current_limit\n"
     "float32 pack_discharge_current_limit\nfloat32 pack_current\nfloat32 pack_voltage\n"
     "float32 pack_amphours\nfloat32 pack_depth_of_discharge\nfloat32 pack_health\n"
     "float32 pack_summed_voltage\nfloat32 total_pack_cycles"),
    ("rkse_driver_interfaces/msg/PowerManagementFeedback",
     "std_msgs/Header header\nbool load_on_off\nbool adc_on_off\nbool card_limit_tripped\n"
     "float32 load_current\nfloat32 bus_voltage\nfloat32 temperature\nfloat32 control_current\n"
     "float32 averaged_time\nfloat32 value_tripped\nfloat32 startup_current\nbool switch_on_off\n"
     "bool watchdog_status\nbool reboot\nbool power_mode_on_off\nbool power_mode_status\n"
     "bool curr_max\nbool curr_max_warn\nbool volt_max\nbool volt_max_warn\nbool volt_min_warn\n"
     "bool volt_min\nbool temp_card_max\nbool temp_card_max_warn"),
    ("sbg_driver/msg/SbgEkfStatus",
     "uint8 solution_mode\nbool attitude_valid\nbool heading_valid\nbool velocity_valid\n"
     "bool position_valid\nbool vert_ref_used\nbool mag_ref_used\nbool gps1_vel_used\n"
     "bool gps1_pos_used\nbool gps1_course_used\nbool gps1_hdt_used\nbool gps2_vel_used\n"
     "bool gps2_pos_used\nbool gps2_course_used\nbool gps2_hdt_used\nbool odo_used"),
    ("sbg_driver/msg/SbgEkfEuler",
     "std_msgs/Header header\nuint32 time_stamp\ngeometry_msgs/Vector3 angle\n"
     "geometry_msgs/Vector3 accuracy\nsbg_driver/SbgEkfStatus status"),
]

all_types = {}
for msgtype, msgdef in custom_msg_defs:
    all_types.update(get_types_from_msg(msgdef, msgtype))
typestore.register(all_types)

bag_path = "/home/alam/post-mission-analysis/20260223_050019_0.db3"

def ts_to_str(ns):
    return datetime.utcfromtimestamp(ns / 1e9).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

output = []

with Reader(bag_path) as reader:

    # ---- MODE TIMELINE ----
    output.append("=" * 70)
    output.append("MODE TIMELINE (/control_mode/status) — first 3 messages")
    output.append("=" * 70)
    count = 0
    for conn, ts, raw in reader.messages():
        if conn.topic == "/control_mode/status" and count < 3:
            msg = typestore.deserialize_cdr(raw, conn.msgtype)
            output.append(f"\n  Timestamp: {ts_to_str(ts)}")
            output.append(f"  KeyValue pairs:")
            for kv in msg.data:
                marker = " <<<< ACTIVE" if kv.value.lower() == "true" else ""
                output.append(f"    {kv.key} = {kv.value}{marker}")
            count += 1

    # ---- FIRST MESSAGE FROM EACH SENSOR TOPIC ----
    topics_to_preview = [
        "/battery_state", "/temperature", "/humidity", "/pressure",
        "/telemetry/state", "/telemetry/battery_state", "/pack_status",
        "/pm/feedback", "/leak_detect", "/gnss/fix", "/odometry/filtered",
        "/moving_base_second/navheading", "/vessel/mode",
        "/imu/ellipse/sbg_ekf_euler",
    ]

    seen = set()
    for conn, ts, raw in reader.messages():
        topic = conn.topic
        if topic in seen or topic not in topics_to_preview:
            continue
        seen.add(topic)

        output.append(f"\n{'=' * 70}")
        output.append(f"{topic} — first message")
        output.append(f"{'=' * 70}")
        output.append(f"  Timestamp: {ts_to_str(ts)}")
        output.append(f"  Mode tag:  Idle (all 597 mode messages show Idle)")

        msg = typestore.deserialize_cdr(raw, conn.msgtype)

        if topic == "/battery_state":
            output.append(f"  voltage:       {msg.voltage}")
            output.append(f"  current:       {msg.current}")
            output.append(f"  charge:        {msg.charge}")
            output.append(f"  capacity:      {msg.capacity}")
            output.append(f"  percentage:    {msg.percentage}")
            output.append(f"  temperature:   {msg.temperature}")
            output.append(f"  present:       {msg.present}")

        elif topic == "/temperature":
            output.append(f"  temperature_c: {msg.temperature}")

        elif topic == "/humidity":
            output.append(f"  relative_humidity: {msg.relative_humidity}")

        elif topic == "/pressure":
            output.append(f"  fluid_pressure: {msg.fluid_pressure}")

        elif topic == "/telemetry/state":
            output.append(f"  latitude:           {msg.latitude}")
            output.append(f"  longitude:          {msg.longitude}")
            output.append(f"  heading:            {msg.heading}")
            output.append(f"  depth:              {msg.depth}")
            output.append(f"  altitude:           {msg.altitude}")
            output.append(f"  vertical_speed:     {msg.vertical_speed}")
            output.append(f"  speed_over_ground:  {msg.speed_over_ground}")
            output.append(f"  course_over_ground: {msg.course_over_ground}")
            output.append(f"  yaw_rate:           {msg.yaw_rate}")

        elif topic == "/telemetry/battery_state":
            output.append(f"  voltage:           {msg.voltage}")
            output.append(f"  charge_percentage: {msg.charge_percentage}")
            output.append(f"  is_charging:       {msg.is_charging}")
            output.append(f"  error_code:        {msg.error_code}")

        elif topic == "/pack_status":
            output.append(f"  pack_state_of_charge: {msg.pack_state_of_charge}")
            output.append(f"  pack_voltage:         {msg.pack_voltage}")
            output.append(f"  pack_current:         {msg.pack_current}")
            output.append(f"  pack_health:          {msg.pack_health}")
            output.append(f"  pack_amphours:        {msg.pack_amphours}")
            output.append(f"  pack_depth_of_discharge: {msg.pack_depth_of_discharge}")
            output.append(f"  discharge_enable:     {msg.discharge_enable}")
            output.append(f"  charge_enable:        {msg.charge_enable}")
            output.append(f"  pack_summed_voltage:  {msg.pack_summed_voltage}")
            output.append(f"  total_pack_cycles:    {msg.total_pack_cycles}")

        elif topic == "/pm/feedback":
            output.append(f"  load_current:  {msg.load_current}")
            output.append(f"  bus_voltage:   {msg.bus_voltage}")
            output.append(f"  temperature:   {msg.temperature}")
            output.append(f"  load_on_off:   {msg.load_on_off}")
            output.append(f"  adc_on_off:    {msg.adc_on_off}")
            if hasattr(msg, 'header') and hasattr(msg.header, 'frame_id'):
                output.append(f"  card_id (tag): {msg.header.frame_id}")

        elif topic == "/leak_detect":
            output.append(f"  status: {msg.data}")

        elif topic == "/gnss/fix":
            output.append(f"  latitude:  {msg.latitude}")
            output.append(f"  longitude: {msg.longitude}")
            output.append(f"  altitude:  {msg.altitude}")
            output.append(f"  status:    {msg.status.status}")
            output.append(f"  service:   {msg.status.service}")

        elif topic == "/odometry/filtered":
            output.append(f"  position:    ({msg.pose.pose.position.x:.6f}, {msg.pose.pose.position.y:.6f}, {msg.pose.pose.position.z:.6f})")
            output.append(f"  orientation: ({msg.pose.pose.orientation.x:.6f}, {msg.pose.pose.orientation.y:.6f}, {msg.pose.pose.orientation.z:.6f}, {msg.pose.pose.orientation.w:.6f})")
            output.append(f"  linear_vel:  ({msg.twist.twist.linear.x:.6f}, {msg.twist.twist.linear.y:.6f}, {msg.twist.twist.linear.z:.6f})")
            output.append(f"  angular_vel: ({msg.twist.twist.angular.x:.6f}, {msg.twist.twist.angular.y:.6f}, {msg.twist.twist.angular.z:.6f})")

        elif topic == "/moving_base_second/navheading":
            output.append(f"  orientation:   ({msg.orientation.x:.6f}, {msg.orientation.y:.6f}, {msg.orientation.z:.6f}, {msg.orientation.w:.6f})")
            output.append(f"  angular_vel:   ({msg.angular_velocity.x:.6f}, {msg.angular_velocity.y:.6f}, {msg.angular_velocity.z:.6f})")

        elif topic == "/vessel/mode":
            output.append(f"  value: {msg.value} (0=STAGING, 1=ACTIVE)")

        elif topic == "/imu/ellipse/sbg_ekf_euler":
            output.append(f"  roll:           {msg.angle.x}")
            output.append(f"  pitch:          {msg.angle.y}")
            output.append(f"  yaw:            {msg.angle.z}")
            output.append(f"  accuracy_roll:  {msg.accuracy.x}")
            output.append(f"  accuracy_pitch: {msg.accuracy.y}")
            output.append(f"  accuracy_yaw:   {msg.accuracy.z}")
            output.append(f"  solution_mode:  {msg.status.solution_mode}")
            output.append(f"  heading_valid:  {msg.status.heading_valid}")
            output.append(f"  position_valid: {msg.status.position_valid}")

with open("/home/alam/influxWithGraphana/extracted-preview.txt", "w") as f:
    f.write("\n".join(output) + "\n")

print(f"Written to /home/alam/influxWithGraphana/extracted-preview.txt")
