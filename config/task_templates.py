"""Task template definitions for topology-only dataset generation.

Templates consume preallocated single-UAV semantic task descriptions. Cluster
planning, task assignment, and executable component parameter filling are
upstream/downstream responsibilities outside this dataset target.

Expected output shape:
{
    "stages": [
        {
            "stage": 0,
            "component": [
                {"id": "c0", "name": "preflight_check", "cmd": "start", "prev": null}
            ]
        },
        {
            "stage": 1,
            "component": [
                {"id": "c1", "name": "takeoff", "cmd": "start", "prev": "c0.success"}
            ]
        }
    ]
}

Design rules:
- The dataset output contains component topology only, never component params.
- Each component action keeps only id, name, cmd, and prev.
- cmd is start or stop. Current first-version templates emit start actions only.
- prev is null, a compact dependency string like "c1.success", or a list of
  dependency strings. Valid events are success and failed.
- prev expresses control dependency, not ROS topic/data dependency.
- Only ROBOT_CTRL components may be used as prev sources.
- SVR components have no control outputs. They are service nodes:
  each required SVR starts at most once, in the same stage as the first
  ROBOT_CTRL component that needs it or in an earlier stage, then keeps
  publishing data through ROS topics.
- Each stage must contain exactly one ROBOT_CTRL start action.
"""

OUTPUT_CONTRACT = {
    "format": "staged_component_actions",
    "contains_component_params": False,
    "contains_component_uuid": False,
    "component_uuid_policy": "downstream_compiler_maps_component_ids_to_uuid",
    "stage_schema": {
        "stage": "stable integer control phase index",
        "component": "component actions emitted in this phase",
    },
    "component_action_schema": {
        "id": "stable local component instance id such as c0",
        "name": "component id from component_library.json",
        "cmd": "start|stop; first-version templates emit start only",
        "prev": "null|'<component_id>.<success|failed>'|list",
    },
    "stage_derivation": "compact control phase centered on exactly one ROBOT_CTRL start action",
    "robot_ctrl_constraint": "exactly one ROBOT_CTRL start action per stage",
    "svr_parallelism": "SVR actions may share the ROBOT_CTRL stage, but cannot drive later control flow",
    "svr_service_node_policy": "required SVR starts once and is reused by later components through topics",
    "svr_prev_source_allowed": False,
}


CONTROL_FLOW_CONSTRAINTS = {
    "prev_source_component_types": ["ROBOT_CTRL"],
    "valid_prev_events": ["success", "failed"],
    "svr_has_control_outputs": False,
    "svr_as_prev_source_allowed": False,
    "svr_start_once_per_task": True,
    "svr_stop_generated": False,
    "data_channel_dependency_policy": "data topics do not create control edges in the training target",
    "robot_ctrl_runtime_policy": "only one ROBOT_CTRL should be active at a time",
}


SVR_GROUPS = {
    "battery_monitoring": ["battery_level", "battery_warning"],
    "position_support": ["get_gnss_position", "gnss_to_position_3d"],
    "waypoint_support": ["waypoint_list_create"],
    "camera_capture": ["sensor_camera_scan"],
    "visible_detection": ["sensor_camera_scan", "object_detect"],
    "thermal_scan": ["sensor_ir_scan"],
    "radar_scan": ["sensor_radar_scan"],
    "gimbal_assist": ["gimbal_control"],
}


PREFLIGHT_RULE = {
    "component": "preflight_check",
    "component_type": "ROBOT_CTRL",
    "position": "first_stage",
    "gates_other_robot_ctrl": True,
}


MOTION_VARIANT_RULES = {
    "ascend": {
        "component": "ascend",
        "insert_after": "takeoff",
        "conditions": ["flight.height_level in ['medium', 'high']"],
        "reason": "adjust from takeoff altitude to mission altitude before the primary route or observation control stage",
    },
    "descend": {
        "component": "descend",
        "insert_before": "return_home",
        "conditions": ["flight.height_level == 'high'"],
        "reason": "leave a high-altitude task phase before return-home and landing sequence",
    },
    "rotate": {
        "component": "rotate",
        "status": "deferred",
        "reason": "requires a clearer observation or heading-alignment semantic trigger before use",
    },
}


SVR_SERVICE_RULES = {
    "battery_monitoring": {
        "components": ["battery_level", "battery_warning"],
        "insert_policy": "same_stage_or_before_first_consumer_robot_ctrl",
        "reuse_policy": "reuse_existing_service_after_first_start",
        "inter_svr_control_edges": False,
    },
    "position_support": {
        "components": ["get_gnss_position", "gnss_to_position_3d"],
        "insert_policy": "same_stage_or_before_goto_point_or_obstacle_avoid_flight",
        "reuse_policy": "reuse_existing_service_after_first_start",
        "inter_svr_control_edges": False,
    },
    "waypoint_support": {
        "components": ["waypoint_list_create"],
        "insert_policy": "same_stage_or_before_waypoint_flight",
        "reuse_policy": "reuse_existing_service_after_first_start",
        "inter_svr_control_edges": False,
    },
    "camera_capture": {
        "components": ["sensor_camera_scan"],
        "insert_policy": "same_stage_or_before_first_visual_consumer_robot_ctrl",
        "reuse_policy": "reuse_existing_service_after_first_start",
        "inter_svr_control_edges": False,
    },
    "visible_detection": {
        "components": ["sensor_camera_scan", "object_detect"],
        "insert_policy": "same_stage_or_before_first_detection_or_tracking_consumer_robot_ctrl",
        "reuse_policy": "reuse_existing_service_after_first_start",
        "inter_svr_control_edges": False,
    },
    "thermal_scan": {
        "components": ["sensor_ir_scan"],
        "insert_policy": "same_stage_or_before_first_thermal_observation_robot_ctrl",
        "reuse_policy": "reuse_existing_service_after_first_start",
        "inter_svr_control_edges": False,
    },
    "radar_scan": {
        "components": ["sensor_radar_scan"],
        "insert_policy": "same_stage_or_before_obstacle_avoid_flight",
        "reuse_policy": "reuse_existing_service_after_first_start",
        "inter_svr_control_edges": False,
    },
}


ROUTE_MODE_RULES = {
    "goto_point": {
        "target_types": ["point"],
        "robot_ctrl_sequence": ["goto_point"],
        "support_svr_groups": ["position_support"],
    },
    "hover": {
        "target_types": ["point"],
        "robot_ctrl_sequence": ["goto_point", "hover"],
        "support_svr_groups": ["position_support"],
    },
    "orbit": {
        "target_types": ["point"],
        "robot_ctrl_sequence": ["goto_point", "orbit_point_flight"],
        "support_svr_groups": ["position_support"],
    },
    "line_follow": {
        "target_types": ["line"],
        "robot_ctrl_sequence": ["waypoint_flight"],
        "support_svr_groups": ["waypoint_support"],
    },
    "corridor_patrol": {
        "target_types": ["line"],
        "robot_ctrl_sequence": ["corridor_patrol_flight"],
        "support_svr_groups": ["waypoint_support"],
    },
    "waypoint": {
        "target_types": ["line", "area"],
        "robot_ctrl_sequence": ["waypoint_flight"],
        "support_svr_groups": ["waypoint_support"],
    },
    "grid": {
        "target_types": ["area"],
        "robot_ctrl_sequence": ["grid_search_flight"],
        "support_svr_groups": [],
    },
    "lawnmower": {
        "target_types": ["area"],
        "robot_ctrl_sequence": ["lawnmower_search_flight"],
        "support_svr_groups": [],
    },
    "perimeter_patrol": {
        "target_types": ["area"],
        "robot_ctrl_sequence": ["perimeter_patrol_flight"],
        "support_svr_groups": ["waypoint_support"],
    },
    "spiral_search": {
        "target_types": ["area"],
        "robot_ctrl_sequence": ["spiral_search_flight"],
        "support_svr_groups": ["position_support"],
    },
    "expanding_square": {
        "target_types": ["area"],
        "robot_ctrl_sequence": ["expanding_square_search"],
        "support_svr_groups": ["position_support"],
    },
}


CAPABILITY_RULES = {
    "image_capture": {
        "requires_payload": "visible_camera",
        "svr_groups": ["camera_capture"],
        "robot_ctrl_components": [],
        "requires_input_fields": [],
    },
    "object_detection": {
        "requires_payload": "visible_camera",
        "svr_groups": ["visible_detection"],
        "robot_ctrl_components": [],
        "requires_input_fields": ["target_classes"],
    },
    "target_tracking": {
        "requires_payload": "visible_camera",
        "svr_groups": ["visible_detection"],
        "robot_ctrl_components": ["target_tracking"],
        "requires_capabilities": ["object_detection"],
        "requires_input_fields": ["target_class"],
    },
    "thermal_scan": {
        "requires_payload": "infrared_camera",
        "svr_groups": ["thermal_scan"],
        "robot_ctrl_components": [],
        "requires_input_fields": [],
    },
    "radar_scan": {
        "requires_payload": "radar",
        "svr_groups": ["radar_scan"],
        "robot_ctrl_components": [],
        "requires_input_fields": [],
        "reason": "radar can be used as a sensing payload without changing the main flight-control component",
    },
    "obstacle_avoidance": {
        "requires_payload": "radar",
        "svr_groups": ["radar_scan"],
        "robot_ctrl_override": "obstacle_avoid_flight",
        "requires_capabilities": ["radar_scan"],
        "requires_input_fields": ["obstacle_level"],
    },
}


TASK_TEMPLATES = {
    "single_uav_area_search": {
        "description": "Area coverage or search after upstream cluster allocation.",
        "target_types": ["area"],
        "allowed_route_modes": [
            "waypoint",
            "grid",
            "lawnmower",
            "perimeter_patrol",
            "spiral_search",
            "expanding_square",
        ],
        "robot_ctrl_backbone": [
            "preflight_check",
            "takeoff",
            "grid_search_flight",
            "return_home",
            "land",
        ],
        "route_mode_source": "input.route_mode",
        "payload_svr_source": "enabled_capabilities",
        "obstacle_avoidance_policy": "replace_waypoint_flight_with_obstacle_avoid_flight",
        "example_topology": {
            "stages": [
                {
                    "stage": 0,
                    "component": [
                        {"id": "c0", "name": "preflight_check", "cmd": "start", "prev": None},
                    ],
                },
                {
                    "stage": 1,
                    "component": [
                        {"id": "c1", "name": "takeoff", "cmd": "start", "prev": "c0.success"},
                    ],
                },
                {
                    "stage": 2,
                    "component": [
                        {"id": "c2", "name": "grid_search_flight", "cmd": "start", "prev": "c1.success"},
                        {"id": "c3", "name": "sensor_camera_scan", "cmd": "start", "prev": "c1.success"},
                        {"id": "c4", "name": "object_detect", "cmd": "start", "prev": "c1.success"},
                    ],
                },
                {
                    "stage": 3,
                    "component": [
                        {"id": "c5", "name": "return_home", "cmd": "start", "prev": "c2.success"},
                    ],
                },
                {
                    "stage": 4,
                    "component": [
                        {"id": "c6", "name": "land", "cmd": "start", "prev": "c5.success"},
                    ],
                },
            ]
        },
    },
    "single_uav_route_inspection": {
        "description": "Line or waypoint inspection for a preallocated route segment.",
        "target_types": ["line"],
        "allowed_route_modes": ["waypoint", "line_follow", "corridor_patrol"],
        "robot_ctrl_backbone": [
            "preflight_check",
            "takeoff",
            "corridor_patrol_flight",
            "return_home",
            "land",
        ],
        "route_mode_source": "input.route_mode",
        "payload_svr_source": "enabled_capabilities",
        "obstacle_avoidance_policy": "replace_waypoint_flight_with_obstacle_avoid_flight",
        "example_topology": {
            "stages": [
                {
                    "stage": 0,
                    "component": [
                        {"id": "c0", "name": "preflight_check", "cmd": "start", "prev": None},
                    ],
                },
                {
                    "stage": 1,
                    "component": [
                        {"id": "c1", "name": "takeoff", "cmd": "start", "prev": "c0.success"},
                    ],
                },
                {
                    "stage": 2,
                    "component": [
                        {"id": "c2", "name": "corridor_patrol_flight", "cmd": "start", "prev": "c1.success"},
                        {"id": "c3", "name": "waypoint_list_create", "cmd": "start", "prev": "c1.success"},
                        {"id": "c4", "name": "sensor_ir_scan", "cmd": "start", "prev": "c1.success"},
                    ],
                },
                {
                    "stage": 3,
                    "component": [
                        {"id": "c5", "name": "return_home", "cmd": "start", "prev": "c2.success"},
                    ],
                },
                {
                    "stage": 4,
                    "component": [
                        {"id": "c6", "name": "land", "cmd": "start", "prev": "c5.success"},
                    ],
                },
            ]
        },
    },
    "single_uav_fixed_point_observation": {
        "description": "Point observation after a single UAV is assigned a fixed target.",
        "target_types": ["point"],
        "allowed_route_modes": ["goto_point", "hover", "orbit"],
        "robot_ctrl_backbone": [
            "preflight_check",
            "takeoff",
            "goto_point",
            "orbit_point_flight",
            "target_tracking",
            "return_home",
            "land",
        ],
        "route_mode_source": "input.route_mode",
        "payload_svr_source": "enabled_capabilities",
        "obstacle_avoidance_policy": "replace_goto_point_with_obstacle_avoid_flight",
        "example_topology": {
            "stages": [
                {
                    "stage": 0,
                    "component": [
                        {"id": "c0", "name": "preflight_check", "cmd": "start", "prev": None},
                    ],
                },
                {
                    "stage": 1,
                    "component": [
                        {"id": "c1", "name": "takeoff", "cmd": "start", "prev": "c0.success"},
                    ],
                },
                {
                    "stage": 2,
                    "component": [
                        {"id": "c2", "name": "goto_point", "cmd": "start", "prev": "c1.success"},
                        {"id": "c3", "name": "get_gnss_position", "cmd": "start", "prev": "c1.success"},
                        {"id": "c4", "name": "gnss_to_position_3d", "cmd": "start", "prev": "c1.success"},
                    ],
                },
                {
                    "stage": 3,
                    "component": [
                        {"id": "c5", "name": "orbit_point_flight", "cmd": "start", "prev": "c2.success"},
                        {"id": "c6", "name": "sensor_camera_scan", "cmd": "start", "prev": "c2.success"},
                        {"id": "c7", "name": "object_detect", "cmd": "start", "prev": "c2.success"},
                    ],
                },
                {
                    "stage": 4,
                    "component": [
                        {"id": "c8", "name": "target_tracking", "cmd": "start", "prev": "c5.success"},
                    ],
                },
                {
                    "stage": 5,
                    "component": [
                        {"id": "c9", "name": "return_home", "cmd": "start", "prev": "c8.success"},
                    ],
                },
                {
                    "stage": 6,
                    "component": [
                        {"id": "c10", "name": "land", "cmd": "start", "prev": "c9.success"},
                    ],
                },
            ]
        },
    },
}


TOPOLOGY_ASSEMBLY_RULES = {
    "topology_kind": "staged_component_actions",
    "valid_commands": ["start", "stop"],
    "emitted_commands": ["start"],
    "valid_prev_events": ["success", "failed"],
    "first_component_prev": None,
    "component_id_policy": {
        "start_defines_component_instance": True,
        "svr_component_name_appears_once_per_task": True,
    },
    "dependency_policy": {
        "prev_expresses_control_flow_only": True,
        "prev_source_component_types": ["ROBOT_CTRL"],
        "allow_svr_as_prev_source": False,
        "allow_data_channel_as_control_edge": False,
        "svr_service_nodes_start_once": True,
        "svr_stop_generated": False,
    },
    "stage_policy": {
        "stage_is_control_phase": True,
        "stage_is_required_to_be_dag_layer": False,
        "exactly_one_robot_ctrl_start_per_stage": True,
        "forbid_svr_only_stage": True,
        "no_stop_actions_in_first_version": True,
    },
    "obstacle_avoidance_policy": {
        "replace_primary_navigation_robot_ctrl": True,
        "robot_ctrl": "obstacle_avoid_flight",
        "required_svr": ["sensor_radar_scan"],
    },
    "invalid_combinations": [
        {
            "condition": "component.prev uses an event other than success or failed",
            "reason": "component control outputs currently expose only success and failed",
        },
        {
            "condition": "stage has zero ROBOT_CTRL start actions or more than one ROBOT_CTRL start action",
            "reason": "each stage must have exactly one control component",
        },
        {
            "condition": "component.cmd == 'stop'",
            "reason": "the first-version topology target starts service nodes once and uses ROBOT_CTRL success/failed to advance the chain",
        },
        {
            "condition": "SVR component appears more than once in a task topology",
            "reason": "SVR service nodes start once and are reused through ROS topics",
        },
        {
            "condition": "component.prev references a component whose type is SVR",
            "reason": "SVR components have no control outputs and cannot drive the topology control flow",
        },
        {
            "condition": "component.name is not defined in component_library.json",
            "reason": "all emitted components must come from the current component set",
        },
        {
            "condition": "target_tracking.enabled == true and object_detection.enabled != true",
            "reason": "target_tracking consumes object_detect bounding boxes",
        },
        {
            "condition": "capability enabled but not supported by selected payload",
            "reason": "each UAV has only one payload",
        },
    ],
}
