# Task Execution Log

Updated: 2026-05-07

## Current Scope

Build a template-only dataset generator for converting preallocated single-UAV
semantic task parameters into structured single-UAV component task stages.

Cluster-level task planning and multi-UAV coordination are upstream
responsibilities and are not part of the first implementation.

## Completed

- Initialized the project with `uv`.
- Created the initial template-only project scaffold.
- Added placeholder directories and files:
  - `config/`
  - `generator/`
  - `raw/`
  - `processed/`
  - `stats/`
- Added `config/component_library.json` based on `component.md`.
- Recorded 23 current components:
  - 10 `ROBOT_CTRL`
  - 13 `SVR`
- Added the core scheduling rule:
  - each output stage must contain exactly one `ROBOT_CTRL`
  - each output stage may contain zero or more `SVR` components
- Defined the project boundary:
  - input comes from upstream cluster-task preallocation
  - this project handles single-UAV semantic task to component-stage conversion
- Added semantic task contract placeholders in `config/task_types.json`.
- Added parameter-space placeholders in `config/params_space.json`.
- Added single-payload constraint:
  - each UAV has exactly one payload in the initial design
- Added explicit capability parameters:
  - image capture
  - thermal scan
  - object detection
  - target tracking
  - obstacle avoidance
- Kept final dataset output as a structured stage sequence rather than platform
  XML flow format.

## Current Output Shape

```json
[
  {
    "stage": 0,
    "robot_ctrl": {
      "component": "takeoff",
      "params": {}
    },
    "svr": []
  },
  {
    "stage": 1,
    "robot_ctrl": {
      "component": "waypoint_flight",
      "params": {}
    },
    "svr": [
      {
        "component": "sensor_camera_scan",
        "params": {}
      },
      {
        "component": "object_detect",
        "params": {}
      }
    ]
  }
]
```

## Next Tasks

- Finalize `task_types.json`:
  - confirm supported single-UAV task types
  - confirm required and optional semantic fields
  - confirm role and route-mode values
- Finalize `params_space.json`:
  - expand realistic task locations and assigned areas
  - fill component parameter ranges
  - confirm payload-to-capability compatibility rules
- Finalize `task_templates.py`:
  - define templates for area search
  - define templates for route inspection
  - define templates for fixed-point observation
  - map semantic capabilities to component stages
- Implement `generator/validator.py`:
  - validate semantic input fields
  - validate single-payload compatibility
  - validate target detection and tracking constraints
  - validate exactly one `ROBOT_CTRL` per stage
  - validate component ids against `component_library.json`
- Implement `generator/template_generator.py`:
  - sample semantic task parameters
  - apply task templates
  - produce raw structured samples
- Implement `generator/pipeline.py`:
  - load config
  - generate raw samples
  - validate and filter samples
  - deduplicate samples
  - split train and validation datasets
  - write distribution report
- Update `main.py` to call the template pipeline.
- Add a small smoke test or sample generation command.

## Open Questions

- Whether obstacle avoidance is possible when each UAV has only one payload and
  the selected payload is not `radar`.
- Whether `target_tracking` should always require `object_detection` in the same
  stage, or only earlier in the same task.
- Whether payload names should remain generic, such as `visible_camera`, or map
  one-to-one to actual platform payload models.
- Whether `return_home` and `land` should always be generated as final stages.
