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

Planned structure:

- `config/component_library.json`: component definitions.
- `config/task_types.json`: supported task types and fields.
- `config/params_space.json`: parameter value spaces.
- `config/task_templates.py`: rule-based task templates.
- `generator/template_generator.py`: template sample generator.
- `generator/validator.py`: generated sample validator.
- `generator/pipeline.py`: generation pipeline entry module.
- `raw/`: raw and intermediate generated data.
- `processed/`: train and validation splits.
- `stats/`: distribution reports.

Output format:

- Generated task output should use an ordered structured stage sequence.
- Each stage contains exactly one `robot_ctrl` component and zero or more `svr`
  components.
- Stage order represents serial control flow. Components inside the same stage
  represent concurrent work.
