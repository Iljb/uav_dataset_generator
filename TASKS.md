# Task Execution Log

Updated: 2026-05-11

## Current Scope

Build a template-only dataset generator for converting preallocated single-UAV
semantic task descriptions into staged single-UAV component actions.

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
- Recorded 22 current components from the updated `component.md`:
  - 12 `ROBOT_CTRL`
  - 10 `SVR`
- Added the core scheduling rule:
  - `stage` is a compact control phase, with `prev` as the explicit control dependency
  - each generated stage must contain exactly one `ROBOT_CTRL` start action
  - `preflight_check` is a `ROBOT_CTRL` gate before other flight-control components
  - `SVR` components have no control outputs and cannot be used as `prev` sources
  - `SVR` components are reusable service nodes: start once when first needed,
    then continue publishing through ROS topics without generated stop actions
- Defined the project boundary:
  - input comes from upstream cluster-task preallocation
  - this project handles single-UAV semantic task to component-stage conversion
- Added semantic task contract placeholders in `config/task_types.json`.
- Added semantic sampling-space placeholders in `config/params_space.json`.
- Added single-payload constraint:
  - each UAV has exactly one payload in the initial design
- Added explicit capability semantics:
  - image capture
  - thermal scan
  - object detection
  - target tracking
  - obstacle avoidance
- Kept final dataset output as structured JSON rather than platform XML flow
  format.
- Finalized the initial `params_space.json` for topology-only template generation:
  - added target definitions for point, line, and area assignments
  - added route-to-ROBOT_CTRL rules for point, line, and area task modes
  - expanded single-payload capability compatibility
  - added capability-to-SVR and safety-to-component mapping rules
- Removed component parameters from the dataset output target:
  - the model should generate component topology only
  - a downstream rule-based step should fill executable component parameters
- Completed the initial `task_templates.py` design:
  - upgraded the output target to compact staged component actions
  - added compact `id/name/cmd/prev` component action fields
  - added route-mode rules for point, line, and area tasks
  - added capability-to-SVR service insertion rules
  - added an obstacle-avoidance ROBOT_CTRL override policy
  - added topology-only examples for the three supported task types
- Updated staged topology semantics for the current component set:
  - removed `sensor_camera_init` references
  - moved `target_tracking` to `ROBOT_CTRL`
  - disallowed SVR-to-component control dependencies
  - kept SVR data relationships in component channels rather than topology `prev`
  - removed generated SVR `stop` actions from template examples
  - ensured each required SVR appears at most once in a task topology
- Implemented `generator/template_generator.py`:
  - loads component, task type, semantic parameter, and template configs
  - validates basic semantic input compatibility before generation
  - builds the serialized `ROBOT_CTRL` backbone from task type and route mode
  - applies obstacle-avoidance and target-tracking control-chain rules
  - resolves required SVR services from safety, route, and capability settings
  - inserts each SVR service once at its first useful `ROBOT_CTRL` stage
  - emits topology-only samples with `semantic_input`, `target_topology`, and metadata
  - includes generator-side invariant checks for stage, `prev`, and SVR reuse rules
- Ran template generation in the `uv` environment:
  - generated 30 valid samples with seed `42`
  - saved semantic seed inputs to `raw/seed_data.json`
  - saved full generated samples to `raw/template_generated.json`
  - saved validation and distribution summary to `stats/distribution_report.json`
- Implemented `generator/validator.py`:
  - validates sample envelope, semantic input, staged topology, control-flow refs, and semantic/component alignment
  - filters generated data into valid and invalid sample sets
  - enforces start-only output, stage continuity, exactly one `ROBOT_CTRL` per stage, no SVR `prev`, no duplicate SVR services, no UUIDs, and no component params
  - provides file-level CLI: `python -m generator.validator --input raw/template_generated.json --output-dir processed --report stats/validation_report.json`
  - saves valid samples to `processed/validated_samples.json`
  - saves invalid samples with issues to `processed/invalid_samples.json`
  - saves validation summary to `stats/validation_report.json`
- Ran validator in the `uv` environment:
  - checked 30 generated samples
  - accepted 30 samples
  - rejected 0 samples
- Implemented `generator/pipeline.py`:
  - orchestrates config loading, template generation, validation, invalid-sample filtering, deduplication, train/val splitting, and report writing
  - defaults to 100 generated samples, seed `42`, validation ratio `0.2`, and no test split
  - removes invalid samples and continues with valid samples by default
  - writes raw seed inputs to `raw/seed_data.json`
  - writes raw generated samples to `raw/template_generated.json`
  - writes valid and invalid validation outputs to `processed/validated_samples.json` and `processed/invalid_samples.json`
  - writes final splits to `processed/train.json` and `processed/val.json`
  - writes distribution, validation, and pipeline reports to `stats/`
  - exposes CLI usage through `python -m generator.pipeline`
  - connects `main.py` to the same pipeline CLI
- Ran the full pipeline in the `uv` environment:
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates
  - wrote 80 train samples and 20 validation samples

## Current Output Shape

```json
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
    },
    {
      "stage": 2,
      "component": [
        {"id": "c2", "name": "waypoint_flight", "cmd": "start", "prev": "c1.success"},
        {"id": "c3", "name": "sensor_camera_scan", "cmd": "start", "prev": "c1.success"}
      ]
    },
    {
      "stage": 3,
      "component": [
        {"id": "c4", "name": "return_home", "cmd": "start", "prev": "c2.success"}
      ]
    },
    {
      "stage": 4,
      "component": [
        {"id": "c5", "name": "land", "cmd": "start", "prev": "c4.success"}
      ]
    }
  ]
}
```

## Next Tasks

- Review `task_types.json`:
  - confirm supported single-UAV task types
  - confirm required and optional semantic fields
  - confirm role and route-mode values
- Review `params_space.json` against real platform values when available:
  - replace placeholder target labels with real mission-area identifiers
  - tune semantic value distributions from simulator or operational data
- Review `task_templates.py`:
  - confirm obstacle-avoidance replacement behavior for multi-waypoint routes
  - confirm whether return-home and land are mandatory for all generated tasks
  - confirm whether `target_tracking` should replace or follow `hover` in fixed-point tasks
- Add automated tests for generator, validator, and pipeline smoke paths.

## Open Questions

- Whether obstacle avoidance should always replace the primary route ROBOT_CTRL,
  or only add `sensor_radar_scan` beside normal route flight for line/area tasks.
- Whether payload names should remain generic, such as `visible_camera`, or map
  one-to-one to actual platform payload models.
- Whether `return_home` and `land` should always be generated as final stages.
