# Phase 0 Baseline Report

Updated: 2026-05-12

## Source

- Git commit: `4c1f4d3`
- Pipeline version: `0.1.0`
- Generator version: `0.1.0`
- Command:

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:PYTHONDONTWRITEBYTECODE = "1"
uv run python -B -m generator.pipeline --count 100 --seed 42 --val-ratio 0.2
```

## Core Metrics

| Metric | Value |
| --- | ---: |
| generated_count | 100 |
| valid_count | 100 |
| invalid_count | 0 |
| deduplicated_count | 100 |
| duplicate_count | 0 |
| train_count | 80 |
| val_count | 20 |
| validation_issue_count | 0 |

## Distribution

### Task Type

| Task Type | Count |
| --- | ---: |
| single_uav_area_search | 29 |
| single_uav_fixed_point_observation | 35 |
| single_uav_route_inspection | 36 |

### Payload

| Payload | Count |
| --- | ---: |
| infrared_camera | 22 |
| radar | 36 |
| visible_camera | 42 |

### Route Mode

| Route Mode | Count |
| --- | ---: |
| goto_point | 18 |
| grid | 10 |
| hover | 17 |
| lawnmower | 11 |
| line_follow | 21 |
| waypoint | 23 |

### Stage Count

| Stage Count | Count |
| --- | ---: |
| 5 | 23 |
| 6 | 39 |
| 7 | 26 |
| 8 | 12 |

### Action Count

| Action Count | Count |
| --- | ---: |
| 9 | 7 |
| 10 | 25 |
| 11 | 33 |
| 12 | 22 |
| 13 | 8 |
| 14 | 5 |

## Component Coverage

### ROBOT_CTRL

| Component | Count |
| --- | ---: |
| ascend | 65 |
| descend | 30 |
| goto_point | 23 |
| hover | 17 |
| land | 100 |
| obstacle_avoid_flight | 36 |
| preflight_check | 100 |
| return_home | 100 |
| takeoff | 100 |
| target_tracking | 15 |
| waypoint_flight | 41 |

### SVR

| Component | Count |
| --- | ---: |
| battery_level | 100 |
| battery_warning | 100 |
| get_gnss_position | 59 |
| gnss_to_position_3d | 59 |
| object_detect | 28 |
| sensor_camera_scan | 42 |
| sensor_ir_scan | 22 |
| sensor_radar_scan | 36 |
| waypoint_list_create | 41 |

## Archived Files

- `phase0_pipeline_report.json`
- `phase0_distribution_report.json`
- `phase0_validation_report.json`

## Regression Criteria

During the refactor, each phase should preserve these minimum guarantees unless the phase explicitly changes generation policy:

- `generated_count = 100`
- `valid_count = 100`
- `invalid_count = 0`
- `duplicate_count = 0`
- `validation_issue_count = 0`
- no component params in output
- no UUIDs in output
- no SVR as `prev` source
- no duplicate SVR service starts
