"""Task template definitions for rule-based dataset generation.

Templates consume single-UAV semantic task parameters. Cluster-level planning and
allocation are upstream responsibilities.

Expected output shape:
[
    {
        "stage": 0,
        "robot_ctrl": {"component": "takeoff", "params": {...}},
        "svr": [{"component": "preflight_check", "params": {...}}],
    },
    ...
]

Each stage must contain exactly one ROBOT_CTRL component and zero or more SVR
components. Payload is a single value per UAV, so capability branches must stay
compatible with that selected payload.

Control-flow rules:
- The output is an ordered JSON array.
- stage values increase from 0 and define serial control-flow order.
- Components within the same stage are considered concurrent.
- robot_ctrl.component must match a ROBOT_CTRL id in component_library.json.
- Every svr[].component must match an SVR id in component_library.json.
- The validator must enforce exactly one ROBOT_CTRL per stage.
"""

TASK_TEMPLATES = {}
