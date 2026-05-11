Template-only UAV dataset generator scaffold.

Initial scope:

- Define component library and task metadata in `config/`.
- Generate samples through rule-based templates only.
- Validate, deduplicate, split, and summarize generated samples.
- Keep LLM-based generation out of the first implementation pass.
- Treat cluster planning as upstream. This project starts from preallocated
  single-UAV semantic task parameters.
- Model each UAV with a single payload. Detection, tracking, thermal scanning,
  and obstacle avoidance must be explicit task parameters.
- Generate component topology only. Component parameters are filled by a
  downstream rule-based step, not by the model training target.
- Treat `preflight_check` as a `ROBOT_CTRL` gating component because other
  flight-control components may start only after it succeeds.
- Treat `SVR` components as leaf/service nodes: they have no control outputs,
  cannot be used as `prev` sources, start once when first needed, and keep
  publishing data through ROS topics.

Planned structure:

- `config/component_library.json`: component definitions.
- `config/task_types.json`: supported task types and fields.
- `config/params_space.json`: semantic sampling spaces and topology mapping rules.
- `config/task_templates.py`: rule-based task templates.
- `generator/template_generator.py`: template sample generator.
- `generator/validator.py`: generated sample validator.
- `generator/pipeline.py`: generation pipeline entry module.
- `raw/`: raw and intermediate generated data.
- `processed/`: train and validation splits.
- `stats/`: distribution reports.

Output format:

- Generated task output should use staged component actions.
- Each stage is a compact control phase with exactly one `ROBOT_CTRL` start
  action and zero or more `SVR` actions.
- Each component action keeps only `id`, `name`, `cmd`, and `prev`.
- `cmd` is retained for platform compatibility. The first-version topology
  target emits `start` actions only.
- `prev` records the predecessor condition, such as `c1.success`. Valid control
  events are `success` and `failed`.
- `prev` may reference only `ROBOT_CTRL` component events. SVR data exchange is
  represented by channels in the component library, not by control edges.
- Random runtime UUIDs are not part of the training target; a downstream compiler
  can assign them when converting to the platform XML flow format.
- Generated task output should not include component parameters.
- SVR actions are inserted at or before the first `ROBOT_CTRL` that needs their
  topic. The same SVR is not inserted again later in the task.
