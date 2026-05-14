# Task Execution Log

Updated: 2026-05-14

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
- Added height-driven motion variants to improve template topology diversity:
  - inserts `ascend` after `takeoff` when `flight.height_level` is `medium` or `high`
  - inserts `descend` before `return_home` when `flight.height_level` is `high`
  - keeps `rotate` deferred until a clearer observation or heading-alignment trigger is defined
  - updated validator expected chains to enforce the same height-variant rules
- Regenerated the dataset through the full `uv` pipeline after adding motion variants:
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - `ascend` appears in 65 samples
  - `descend` appears in 30 samples
  - remaining unused components: `rotate`, `gimbal_control`
- Added `REFACTOR_PLAN.md` for the role-driven refactor:
  - recorded current generator and validator coupling points
  - defined role-based component resolution, service dependency resolution, config linting, and optional failure-strategy chains
  - kept failure-strategy chains out of the minimum viable refactor scope
- Established the Phase 0 baseline reports:
  - saved pipeline, distribution, validation, and summary reports under `stats/baseline/`
  - baseline command: `uv run python -B -m generator.pipeline --count 100 --seed 42 --val-ratio 0.2`
  - generated 100 samples, accepted 100 samples, rejected 0 samples, removed 0 duplicates
- Added semantic annotations to all 22 components in `component_library.json`:
  - added `roles`, `consumes_topics`, `provides_topics`, `lifecycle`, `selection_weight`, `enabled`, and `status`
  - marked 20 components as `active`
  - marked `rotate` and `gimbal_control` as `deferred`
  - marked 12 `ROBOT_CTRL` components as `control_once`
  - marked 10 `SVR` components as `service_persistent`
  - verified topic annotations match existing input and output channels
- Reran the full `uv` pipeline after component semantic annotation:
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates
- Implemented Phase 1 refactor support modules:
  - added `generator/component_index.py`
  - added `generator/config_linter.py`
  - indexed components by id, type, role, topic provider, topic consumer, lifecycle, and status
  - added config lint checks for semantic fields, component type consistency, lifecycle consistency, control outputs, topic annotation consistency, required active roles, topic providers, and mapping references
  - exposed `python -m generator.config_linter`
  - connected config linting to `generator.pipeline` before sample generation
  - exposed component index and config linter helpers through `generator.__init__`
- Ran config linting:
  - saved report to `stats/config_lint_report.json`
  - valid: true
  - errors: 0
  - warnings: 0
- Reran the full `uv` pipeline after connecting config linting:
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates
- Added the initial abstract planner without replacing the legacy generator:
  - added `route_to_roles` beside the existing `route_to_robot_ctrl` mapping
  - added `generator/planner.py`
  - planner emits abstract `robot_roles` and `service_roles` only
  - planner output does not contain component ids and does not resolve concrete components
  - exposed `python -m generator.planner`
  - exposed planner helpers through `generator.__init__`
  - extended `config_linter.py` to validate `route_to_roles`
  - verified 100 legacy generated samples project to the same robot role chains as planner output
- Reran config linting and the full `uv` pipeline after adding the planner:
  - config lint valid: true
  - config lint errors: 0
  - config lint warnings: 0
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates
- Implemented role resolution and replaced the legacy hardcoded ROBOT_CTRL chain:
  - added `generator/role_resolver.py`
  - resolves abstract `ROBOT_CTRL` roles to concrete active components through `component_library.json` roles
  - uses deterministic selection: highest `selection_weight`, then component-library order
  - exposed role resolver helpers through `generator.__init__`
  - replaced `template_generator.build_robot_ctrl_chain()` with `build_abstract_plan()` + `resolve_robot_role_chain()`
  - removed the old hardcoded main-chain helper logic from `template_generator.py`
  - verified 100 generated samples produce identical ROBOT_CTRL chains compared with the legacy logic
- Reran validation after replacing the generator chain:
  - config lint valid: true
  - config lint errors: 0
  - config lint warnings: 0
  - legacy-chain comparison checked 100 samples with 0 mismatches
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates
- Implemented SVR service dependency resolution and replaced the legacy hardcoded SVR logic:
  - added `generator/service_resolver.py`
  - resolves service roles from the abstract planner and concrete SVR components from `component_library.json`
  - completes required SVR services through required topic dependencies
  - places SVR services by semantic role priority and direct ROBOT_CTRL topic consumers
  - keeps global safety services at stage 0
  - preserves the rule that each SVR starts at most once and never becomes a control-flow `prev`
  - replaced `template_generator.resolve_required_svr()` and `template_generator.attach_svr_services()`
  - exposed service resolver helpers through `generator.__init__`
- Reran validation after replacing SVR resolution:
  - config lint valid: true
  - config lint errors: 0
  - config lint warnings: 0
  - legacy-SVR comparison checked 100 samples with 0 mismatches
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates
  - compile check passed for `generator/`
- Refactored validator semantic alignment to role coverage:
  - kept topology structure validation independent
  - replaced component-name expected-chain checks with planner-derived ROBOT_CTRL role chain checks
  - replaced component-name SVR expectation checks with service role coverage checks
  - added required topic provider validation using component `consumes_topics` and `provides_topics`
  - flags providers that start after their consumers
  - flags unexpected SVR services unless they satisfy a required service role or required topic
  - removed legacy `_expected_robot_ctrl_chain()`, `_expected_svr_services()`, and component-set presence checks from `validator.py`
- Reran validation after role-aware validator refactor:
  - config lint valid: true
  - config lint errors: 0
  - config lint warnings: 0
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates
  - compile check passed for `generator/`
  - manual negative samples were rejected for missing robot role, missing service role, unknown component, SVR `prev`, and duplicate SVR
- Implemented Phase 6 optional failure-strategy branch support:
  - added `failure_strategy_rules` to `params_space.json`, defaulting to disabled
  - added `generator/control_graph.py` for resolved ROBOT_CTRL control graph representation
  - added `generator/failure_strategy.py` for deterministic safe failure branch selection
  - kept default generation on the main success chain with no failure branches
  - added graph-based topology assembly in `template_generator.py`
  - emits failure metadata under `metadata.failure_strategy`
  - extended `config_linter.py` to validate failure policy trigger and branch roles
  - extended validator to support guarded stages when failure strategies are enabled
  - validator now checks mutually exclusive ROBOT_CTRL guards, safe failure branch terminals, and policy matching
  - pipeline reports now include `failure_enabled_count`, `failure_branch_count`, `guarded_robot_ctrl_stage_count`, and `by_failure_policy`
- Reran validation after Phase 6 support:
  - default failure strategy disabled
  - config lint valid: true
  - config lint errors: 0
  - config lint warnings: 0
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates
  - failure-enabled samples generated in memory: 100
  - failure-enabled samples accepted in memory: 100
  - manual negative samples were rejected for non-mutually-exclusive guards, missing safe terminal, and failed edges while disabled
- Enabled failure strategies by default and regenerated persisted samples:
  - set `failure_strategy_rules.enabled` to `true`
  - set `failure_strategy_default_enabled` to `true`
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates by current sample-id/content dedupe
  - failure-enabled samples: 100
  - failure branches: 100
  - guarded ROBOT_CTRL stages: 200
  - active failure policy: `safe_return`
- Checked topology-only duplicate structures:
  - saved report to `stats/topology_duplicate_report.json`
  - exact `target_topology` unique count: 33 / 100
  - exact duplicate topology groups: 23
  - exact duplicate topology sample count: 90
  - largest exact topology group size: 12
  - component-stage signature unique count: 33 / 100
  - normalized-prev shape unique count: 33 / 100
- Improved failure-strategy branch diversity:
  - added `complexity` to generated semantic input
  - added `branch_count_by_complexity`:
    - `simple`: 0 or 1 failure branches
    - `medium`: 1 or 2 failure branches
    - `complex`: 2 or 3 failure branches
  - increased `max_branches_per_task` to 3
  - added `policy_selection: balanced_by_trigger_role`
  - updated failure strategy selection to rotate among applicable policies instead of always selecting `safe_return`
  - preserved one failure strategy per trigger component
  - extended config lint checks for branch-count ranges and policy-selection mode
- Regenerated persisted samples after failure-strategy diversity:
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates by current sample-id/content dedupe
  - failure-enabled samples: 100
  - failure branches: 146
  - guarded ROBOT_CTRL stages: 212
  - `by_failure_policy`: `safe_land` 77, `safe_return` 54, `hold_then_return` 15
  - complexity distribution: `simple` 33, `medium` 33, `complex` 34
  - branch-count distribution:
    - `simple:0` 19, `simple:1` 14
    - `medium:1` 18, `medium:2` 15
    - `complex:2` 18, `complex:3` 16
  - exact `target_topology` unique count improved to 67 / 100
  - exact duplicate topology groups reduced to 18
  - largest exact topology group size reduced to 6
- Added default topology diversity strategies without a plugin switch:
  - height action variants:
    - `high` height always inserts `ascend`
    - `medium` height inserts `ascend` by deterministic complexity-weighted choice
    - `high` height inserts `descend` by deterministic complexity-weighted choice
  - optional observation/stabilization stages:
    - observation-related tasks may add a `hover` control stage before tracking or mission tail
    - existing `hover` route stages are not duplicated
  - SVR service start-stage variants:
    - non-global SVR services may start one or two stages earlier by deterministic complexity-weighted choice
    - topic provider order is still enforced so providers never start later than consumers
- Regenerated persisted samples after default topology diversity:
  - generated 100 samples
  - accepted 100 samples
  - rejected 0 samples
  - removed 0 duplicates by current sample-id/content dedupe
  - failure-enabled samples: 100
  - failure branches: 148
  - guarded ROBOT_CTRL stages: 217
  - `by_failure_policy`: `safe_land` 69, `safe_return` 51, `hold_then_return` 28
  - component usage highlights:
    - `ascend`: 52
    - `descend`: 18
    - `hover`: 71
  - exact `target_topology` unique count improved to 96 / 100
  - exact duplicate topology groups reduced to 4
  - largest exact topology group size reduced to 2
  - saved per-component stage distributions in `stats/topology_duplicate_report.json`

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
- Design deferred component usage:
  - define a clear semantic trigger before introducing `rotate`
  - decide whether `gimbal_control` belongs in topology generation or downstream parameter/payload control
- Review Phase 6 failure-strategy behavior:
  - decide whether `safe_return` should attach to all navigation roles or only high-risk roles
  - decide whether failure branch metadata should remain outside the model training target
- Reduce topology-only duplicates:
  - add topology-structure deduplication or coverage-aware rejection in `pipeline.py`
  - consider policy selection based on task type, risk level, or payload
  - consider whether remaining exact duplicate topologies should be filtered or kept as semantic paraphrase variants
- Add focused automated smoke tests:
  - config lint
  - template generation
  - validator acceptance/rejection
  - pipeline count and split behavior

## Open Questions

- Whether obstacle avoidance should always replace the primary route ROBOT_CTRL,
  or only add `sensor_radar_scan` beside normal route flight for line/area tasks.
- Whether payload names should remain generic, such as `visible_camera`, or map
  one-to-one to actual platform payload models.
- Whether `return_home` and `land` should always be generated as final stages.
