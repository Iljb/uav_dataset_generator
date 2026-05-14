# ATSComponents 组件总览

本文档按当前仓库 `src/*/launch/component.ats` 实际配置整理。  
更新时间：2026-05-13  
组件总数：29（`ROBOT_CTRL` 19，`SVR` 10）

## 类型规则

- `ROBOT_CTRL`：直接控制无人机飞行（向飞控输出动作指令）。
- `SVR`：数据处理/感知/传输类组件，不直接控制飞行，不通过控制输出驱动 DAG。
- 调度建议：同一时刻通常只运行 1 个 `ROBOT_CTRL`；`SVR` 可并行运行，start 后持续运行，直到收到 stop。

## 字段说明

- `控制端口`：`inport` 的 `start/stop` 使能。
- `输入通道`：`sub_channels`。
- `输出通道`：`pub_channels`。
- `控制输出`：`outports`（`ROBOT_CTRL` 可使用 `success` / `failed`；`SVR` 统一无控制输出）。
- `关键参数`：仅列参数名，具体含义见对应 `component.ats` 的 `description`。

## ROBOT_CTRL 组件（19）

| 组件 | 启动命令 | 控制端口 | 输入通道 | 输出通道 | 控制输出 | 关键参数 |
|---|---|---|---|---|---|---|
| `preflight_check` | `roslaunch preflight_check preflight_check.launch` | `start=true, stop=true` | 无 | 无 | `success, failed` | `timeout_sec, min_battery_percent, require_gps_fix, max_gps_horizontal_std_m` |
| `takeoff` | `roslaunch takeoff takeoff.launch` | `start=true, stop=false` | 无 | 无 | `success, failed` | `height, timeout_sec, height_tolerance` |
| `land` | `roslaunch land land.launch` | `start=true, stop=false` | 无 | 无 | `success, failed` | `timeout_sec, landed_height_threshold` |
| `hover` | `roslaunch hover hover.launch` | `start=true, stop=false` | 无 | 无 | `success, failed` | `duration_sec, position_tolerance` |
| `ascend` | `roslaunch ascend ascend.launch` | `start=true, stop=false` | 无 | 无 | `success, failed` | `delta_z, timeout_sec, height_tolerance` |
| `descend` | `roslaunch descend descend.launch` | `start=true, stop=false` | 无 | 无 | `success, failed` | `delta_z, min_z, timeout_sec, height_tolerance` |
| `rotate` | `roslaunch rotate rotate.launch` | `start=true, stop=false` | 无 | 无 | `success, failed` | `delta_yaw_deg, timeout_sec, yaw_tolerance_deg` |
| `goto_point` | `roslaunch goto_point goto_point.launch` | `start=true, stop=false` | `/position/positon_3d` (`geometry_msgs/PoseStamped`) | 无 | `success, failed` | `x, y, z, yaw, timeout_sec, position_tolerance, yaw_tolerance_deg` |
| `waypoint_flight` | `roslaunch waypoint_flight waypoint_flight.launch` | `start=true, stop=false` | `/position/positon_3d_array` (`gnss_to_position_3d/Position3DWaypointArray`) | `/waypoint_flight/reached` (`std_msgs/Int32`), `/waypoint_flight/action_cmd` (`std_msgs/Int32`) | `success, failed` | `waypoints, timeout_sec, hold_sec, waypoint_action, action_hold_sec, position_tolerance, yaw_tolerance_deg` |
| `return_home` | `roslaunch return_home return_home.launch` | `start=true, stop=false` | `/battery_level/state` (`sensor_msgs/BatteryState`, 可选) | 无 | `success, failed` | `timeout_sec, landed_height_threshold, enable_low_battery_auto_return, low_battery_threshold_percent` |
| `obstacle_avoid_flight` | `roslaunch obstacle_avoid_flight obstacle_avoid_flight.launch` | `start=true, stop=true` | `/position/positon_3d` (`geometry_msgs/PoseStamped`), `/sensor_radar_scan/scan` (`sensor_msgs/LaserScan`) | `/obstacle_avoid_flight/planned_setpoint` (`geometry_msgs/PoseStamped`) | `success, failed` | `x, y, z, yaw, timeout_sec, position_tolerance, yaw_tolerance_deg, obstacle_distance_threshold_m, front_fov_deg, side_fov_deg, avoid_lateral_step_m, avoid_forward_step_m, avoid_vertical_step_m, avoid_hold_sec, max_altitude_m, scan_timeout_sec` |
| `target_tracking` | `roslaunch target_tracking target_tracking.launch` | `start=true, stop=true` | `/vision/object_detect/bounding_boxes` (`object_detect/BoundingBoxes`) | 无 | `success, failed` | `target_class_id, min_confidence, min_iou_for_association, max_center_distance_px, max_lost_time_sec, smoothing_alpha` |
| `orbit_point_flight` | `roslaunch orbit_point_flight orbit_point_flight.launch` | `start=true, stop=false` | `/position/positon_3d` (`geometry_msgs/PoseStamped`, 可选) | `/orbit_point_flight/current_setpoint` (`geometry_msgs/PoseStamped`) | `success, failed` | `center_x, center_y, center_z, altitude, radius, laps, speed_mps, clockwise, timeout_sec, position_tolerance` |
| `corridor_patrol_flight` | `roslaunch corridor_patrol_flight corridor_patrol_flight.launch` | `start=true, stop=false` | `/position/positon_3d_array` (`gnss_to_position_3d/Position3DWaypointArray`, 可选) | `/corridor_patrol_flight/current_setpoint` (`geometry_msgs/PoseStamped`) | `success, failed` | `route_points, altitude, corridor_width, speed_mps, repeat_count, timeout_sec, position_tolerance` |
| `perimeter_patrol_flight` | `roslaunch perimeter_patrol_flight perimeter_patrol_flight.launch` | `start=true, stop=false` | `/position/positon_3d_array` (`gnss_to_position_3d/Position3DWaypointArray`, 可选) | `/perimeter_patrol_flight/current_setpoint` (`geometry_msgs/PoseStamped`) | `success, failed` | `boundary_points, altitude, speed_mps, repeat_count, clockwise, timeout_sec, position_tolerance` |
| `lawnmower_search_flight` | `roslaunch lawnmower_search_flight lawnmower_search_flight.launch` | `start=true, stop=false` | 无 | `/lawnmower_search_flight/current_setpoint` (`geometry_msgs/PoseStamped`) | `success, failed` | `center_x, center_y, altitude, length, width, lane_spacing, speed_mps, timeout_sec, position_tolerance` |
| `grid_search_flight` | `roslaunch grid_search_flight grid_search_flight.launch` | `start=true, stop=false` | 无 | `/grid_search_flight/current_setpoint` (`geometry_msgs/PoseStamped`) | `success, failed` | `center_x, center_y, altitude, length, width, grid_spacing, speed_mps, timeout_sec, position_tolerance` |
| `spiral_search_flight` | `roslaunch spiral_search_flight spiral_search_flight.launch` | `start=true, stop=false` | `/position/positon_3d` (`geometry_msgs/PoseStamped`, 可选) | `/spiral_search_flight/current_setpoint` (`geometry_msgs/PoseStamped`) | `success, failed` | `center_x, center_y, altitude, max_radius, spacing, speed_mps, timeout_sec, position_tolerance` |
| `expanding_square_search` | `roslaunch expanding_square_search expanding_square_search.launch` | `start=true, stop=false` | `/position/positon_3d` (`geometry_msgs/PoseStamped`, 可选) | `/expanding_square_search/current_setpoint` (`geometry_msgs/PoseStamped`) | `success, failed` | `center_x, center_y, altitude, max_size, spacing, speed_mps, timeout_sec, position_tolerance` |

## SVR 组件（10）

| 组件 | 启动命令 | 控制端口 | 输入通道 | 输出通道 | 控制输出 | 关键参数 |
|---|---|---|---|---|---|---|
| `battery_level` | `roslaunch battery_level battery_level.launch` | `start=true, stop=true` | 无 | `/battery_level/state` (`sensor_msgs/BatteryState`), `/battery_level/percentage` (`std_msgs/Float32`) | 无 | 无 |
| `battery_warning` | `roslaunch battery_warning battery_warning.launch` | `start=true, stop=true` | `/battery_level/percentage` (`std_msgs/Float32`) | `/battery_warning/warning` (`std_msgs/Bool`) | 无 | `warning_threshold_percent` |
| `get_gnss_position` | `roslaunch get_gnss_position get_gnss_position.launch` | `start=true, stop=true` | 无 | `/position/gnss_postion` (`sensor_msgs/NavSatFix`) | 无 | `gnss_system, max_horizontal_std_m, max_vertical_std_m` |
| `gnss_to_position_3d` | `roslaunch gnss_to_position_3d gnss_to_position_3d.launch` | `start=true, stop=true` | `/position/gnss_postion` (`sensor_msgs/NavSatFix`) | `/position/positon_3d` (`geometry_msgs/PoseStamped`) | 无 | `origin_latitude_deg, origin_longitude_deg, origin_altitude_m` |
| `waypoint_list_create` | `roslaunch waypoint_list_create waypoint_list_create.launch` | `start=true, stop=true` | 无 | `/position/positon_3d_array` (`gnss_to_position_3d/Position3DWaypointArray`) | 无 | `gnss_waypoints, origin_latitude_deg, origin_longitude_deg, origin_altitude_m` |
| `sensor_camera_scan` | `roslaunch sensor_camera_scan sensor_camera_scan.launch` | `start=true, stop=true` | 无 | `/visible_camera/video_frame` (`sensor_msgs/Image`) | 无 | `frame_rate_hz, resolution_width, resolution_height` |
| `sensor_radar_scan` | `roslaunch sensor_radar_scan sensor_radar_scan.launch` | `start=true, stop=true` | 无 | `/sensor_radar_scan/scan` (`sensor_msgs/LaserScan`) | 无 | `min_valid_range_m, max_valid_range_m` |
| `sensor_ir_scan` | `roslaunch sensor_ir_scan sensor_ir_scan.launch` | `start=true, stop=true` | 无 | `/sensor_ir_scan/thermal_image` (`sensor_msgs/Image`), `/sensor_ir_scan/temperature_measurement` (`sensor_msgs/Temperature`) | 无 | `scan_mode, frame_rate_hz, emissivity, temperature_min_c, temperature_max_c, measurement_distance_m` |
| `object_detect` | `roslaunch object_detect object_detect.launch` | `start=true, stop=true` | `/visible_camera/video_frame` (`sensor_msgs/Image`，优先) | `/vision/object_detect/bounding_boxes` (`object_detect/BoundingBoxes`), `/vision/object_detect/visualized_image` (`sensor_msgs/Image`) | 无 | `camera_topic, model_path, class_names_path, confidence_threshold, nms_threshold, input_width, input_height, max_detections` |
| `gimbal_control` | `roslaunch gimbal_control gimbal_control.launch` | `start=true, stop=true` | 无 | 无 | 无 | `vel` |

## 备注

- 当前 topic 命名中存在历史兼容拼写：`gnss_postion`、`positon_3d`。文档保持与代码一致。
- 如果后续统一修正命名，建议同步更新 `component.ats`、节点代码和本总览文档。
- `sensor_camera_init` 已删除，相机就绪检查由 `sensor_camera_scan` 启动后的图像流等待与超时日志承担。
- `object_detect` 输入图像源优先取 `sub_channels[0]`；若未配置输入通道，则回退到参数 `camera_topic`（默认 `/sensors/visible_camera/image_raw`）。
- 新增侦察巡检飞行任务组件按点、线、面组织：点任务为绕点飞行；线任务为走廊巡检和周界巡检；面任务为割草机、网格、螺旋和扩展方形搜索。
