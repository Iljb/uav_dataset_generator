# UAV Dataset Generator Refactor Plan

Updated: 2026-05-12

## 1. 结论

当前“组件名驱动”的模板生成方案可以继续工作，但扩展性已经接近边界。只要组件库发生变化，例如组件重命名、新增替代组件、修改输入输出 topic、调整组件类型，`template_generator.py` 和 `validator.py` 都可能需要同步修改。这会带来两个问题：

- 组件变更成本高：组件知识散落在配置和 Python 代码里。
- 样本多样性受限：生成器倾向输出固定组件链，拓扑结构相似度偏高。

建议进行一次渐进式重构，把系统从“组件名驱动”改成“语义角色驱动 + 配置规则驱动”。重构后，Python 代码主要负责通用规划、解析、装配和校验；组件知识、任务规则、插入策略和多样性策略尽量由配置表达。

该方案技术上可行，并且不会天然降低当前生成效果。关键是第一阶段必须保持兼容：同一 seed 下，重构前后的核心统计结果应基本一致，之后再逐步开放多候选组件和拓扑变体。

## 2. 当前问题分析

### 2.1 生成器耦合点

当前 `generator/template_generator.py` 里存在以下硬编码：

- `build_robot_ctrl_chain()` 直接写死基础飞控链：
  - `preflight_check`
  - `takeoff`
  - `return_home`
  - `land`
- `_height_entry_variants()` 和 `_height_exit_variants()` 直接返回：
  - `ascend`
  - `descend`
- `_replace_primary_navigation()` 直接识别并替换：
  - `waypoint_flight`
  - `goto_point`
  - `obstacle_avoid_flight`
- `resolve_required_svr()` 直接判断飞控链中是否存在特定组件，再插入 SVR：
  - `get_gnss_position`
  - `gnss_to_position_3d`
  - `waypoint_list_create`
- `_first_consumer_stage()` 通过组件名判断 SVR 应插入哪个 stage。

这些逻辑不是纯算法，而是组件库知识。如果组件库调整，代码必须同步调整。

### 2.2 校验器耦合点

当前 `generator/validator.py` 里重复实现了部分生成逻辑：

- `_expected_robot_ctrl_chain()` 重新推导预期飞控链。
- `_expected_svr_services()` 重新推导预期 SVR。
- `_validate_required_component_presence()` 直接写死不同语义任务必须出现的组件集合。

这会导致生成器和校验器形成“双份业务规则”。当生成规则改变时，校验器也要同步修改，否则会出现两类风险：

- 生成器正确但校验器误判。
- 生成器错误但校验器因为复制了同样的错误而放行。

### 2.3 配置层不足

当前 `component_library.json` 已经有组件类型、输入 topic、输出 topic、参数等信息，但缺少组件语义层：

- 组件承担什么任务角色不明确。
- 哪些组件可以互为替代不明确。
- 哪些组件是基础飞控、任务动作、感知服务或安全服务不明确。
- `rotate`、`gimbal_control` 这类组件缺少明确触发语义，难以安全引入。

当前 `params_space.json` 中仍有 `route_to_robot_ctrl`、`capability_to_svr`、`safety_to_component` 等直接组件映射，这些配置比写死在代码里好，但仍然是组件名级别，而不是语义角色级别。

## 3. 重构目标

### 3.1 架构目标

重构后的主流程应变为：

```text
semantic_input
  -> abstract_plan
  -> role_resolution
  -> failure_strategy_planning
  -> data/service_dependency_resolution
  -> stage_assembly
  -> validation
  -> reporting
```

其中：

- `abstract_plan` 表示任务需要哪些抽象动作或服务。
- `role_resolution` 把抽象角色映射为具体组件。
- `failure_strategy_planning` 在主控制链完成后，为部分关键控制组件追加失败处理分支。
- `data/service_dependency_resolution` 根据组件输入输出 topic 和显式服务规则补全 SVR。
- `stage_assembly` 只负责生成当前训练目标格式。
- `validation` 校验结构、角色覆盖、依赖完整性和分布质量。

### 3.2 样本目标

重构后仍保持当前训练目标不变：

```json
{
  "stages": [
    {
      "stage": 0,
      "component": [
        {"id": "c0", "name": "preflight_check", "cmd": "start", "prev": null}
      ]
    }
  ]
}
```

即：

- 不生成组件参数。
- 不生成 UUID。
- `prev` 只表达控制流。
- 第一阶段仍保持每个 stage 有且只有一个 `ROBOT_CTRL`。
- 引入失败策略链后，静态 stage 可包含多个 `ROBOT_CTRL`，但它们必须处在互斥控制条件下；任意一条实际运行路径上，同一时刻仍然只能启动一个 `ROBOT_CTRL`。
- SVR 只作为服务节点启动一次，不作为控制流前驱。

### 3.3 维护目标

组件变化后，优先只修改配置：

- 新增组件：在组件库中声明角色、类型、topic 和权重。
- 替换组件：调整角色候选或权重。
- 删除组件：配置自检报告缺失角色，再补充替代组件或禁用相关规则。
- 修改 topic：更新组件库的输入输出 topic，由依赖解析器自动重新推导 SVR。

## 4. 目标架构设计

### 4.1 组件语义索引

在 `component_library.json` 中为每个组件增加语义字段。建议字段如下：

```json
{
  "id": "waypoint_flight",
  "type": "ROBOT_CTRL",
  "roles": [
    "navigation.path",
    "navigation.line",
    "navigation.area"
  ],
  "provides_topics": [
    "/waypoint_flight/reached",
    "/waypoint_flight/action_cmd"
  ],
  "consumes_topics": [
    "/position/positon_3d_array"
  ],
  "lifecycle": "control_once",
  "selection_weight": 1.0,
  "enabled": true
}
```

说明：

- `roles`：组件承担的语义角色。
- `provides_topics`：组件长期提供的数据 topic。
- `consumes_topics`：组件运行前或运行中依赖的数据 topic。
- `lifecycle`：组件生命周期策略。
- `selection_weight`：同角色多候选时的选择权重。
- `enabled`：临时禁用组件时不需要删除组件定义。

当前组件可先标注为：

| 组件 | 建议角色 |
| --- | --- |
| `preflight_check` | `flight.preflight` |
| `takeoff` | `flight.takeoff` |
| `ascend` | `flight.altitude_up` |
| `descend` | `flight.altitude_down` |
| `goto_point` | `navigation.point` |
| `waypoint_flight` | `navigation.path`, `navigation.line`, `navigation.area` |
| `hover` | `observation.hover` |
| `return_home` | `flight.return` |
| `land` | `flight.land` |
| `obstacle_avoid_flight` | `navigation.obstacle_avoid` |
| `target_tracking` | `tracking.target` |
| `battery_level` | `service.battery.level` |
| `battery_warning` | `service.battery.warning` |
| `get_gnss_position` | `service.position.gnss` |
| `gnss_to_position_3d` | `service.position.local_pose` |
| `waypoint_list_create` | `service.route.waypoint_list` |
| `sensor_camera_scan` | `service.camera.visible` |
| `sensor_ir_scan` | `service.camera.thermal` |
| `sensor_radar_scan` | `service.radar.scan` |
| `object_detect` | `service.vision.detect` |
| `rotate` | `motion.heading_rotate`, status deferred |
| `gimbal_control` | `service.gimbal.control`, status deferred |

`rotate` 和 `gimbal_control` 暂不进入默认生成链，直到语义输入中有明确触发字段，例如 `observation_heading_scan`、`target_recenter` 或 `gimbal_required`。

### 4.2 抽象任务计划

任务模板不应直接描述组件名，而应描述角色链。

示例：

```json
{
  "base_robot_roles": [
    "flight.preflight",
    "flight.takeoff",
    "navigation.primary",
    "flight.return",
    "flight.land"
  ]
}
```

然后由规则把语义字段展开：

```text
route_mode = goto_point
  -> navigation.primary = navigation.point

route_mode = waypoint | line_follow | grid | lawnmower
  -> navigation.primary = navigation.path

capabilities.obstacle_avoidance.enabled = true
  -> replace navigation.primary with navigation.obstacle_avoid

flight.height_level in [medium, high]
  -> insert flight.altitude_up after flight.takeoff

flight.height_level = high
  -> insert flight.altitude_down before flight.return

capabilities.target_tracking.enabled = true
  -> append tracking.target after observation/navigation phase
```

这样模板表达的是任务结构，而不是当前具体组件集合。

### 4.3 角色解析器

新增角色解析器 `RoleResolver`，职责是：

```text
role + constraints + selection_policy -> concrete component id
```

输入：

- 角色名，例如 `navigation.path`。
- 组件类型约束，例如必须是 `ROBOT_CTRL`。
- payload 约束。
- capability 约束。
- 权重和覆盖率目标。

输出：

- 一个具体组件 id，例如 `waypoint_flight`。

第一阶段每个角色只映射到当前已有组件，以保持结果稳定。后续如果同一角色出现多个候选组件，再开启加权选择。

### 4.4 服务依赖解析器

SVR 插入不应继续依赖 `_first_consumer_stage()` 这种组件名判断。建议改为两条规则联合：

1. 显式语义服务规则。

   例如：

   ```text
   image_capture -> service.camera.visible
   object_detection -> service.camera.visible + service.vision.detect
   target_tracking -> service.camera.visible + service.vision.detect
   obstacle_avoidance -> service.radar.scan
   battery_monitor -> service.battery.level + service.battery.warning
   ```

2. topic 闭包依赖推导。

   如果某个已选组件 `consumes_topics` 中存在 topic，则寻找能 `provides_topics` 该 topic 的 SVR。找到后加入 required services。若这个 SVR 又依赖其他 topic，则继续递归解析。

示例：

```text
waypoint_flight consumes /position/positon_3d_array
waypoint_list_create provides /position/positon_3d_array
=> insert waypoint_list_create
```

```text
object_detect consumes /visible_camera/video_frame
sensor_camera_scan provides /visible_camera/video_frame
=> insert sensor_camera_scan
```

插入策略：

- 每个 SVR 在同一任务拓扑中最多出现一次。
- SVR 插入在第一个消费者所在 stage，或该 stage 之前。
- SVR 的 `prev` 与所在 stage 的 `ROBOT_CTRL` 保持一致。
- SVR 不产生控制边，不作为任何后续组件的 `prev` 来源。

注意：仅靠 topic 推导无法处理所有情况。`battery_warning`、`gimbal_control` 等组件仍需要显式服务规则或触发语义。

### 4.5 Stage 装配器

`StageAssembler` 应保持通用，不理解任务语义。

输入：

```text
resolved_control_graph:
  robot_nodes: [component_id]
  control_edges: [prev_node.event -> next_node]
stage_services: {stage_index: [svr_component_id]}
```

输出：

```json
{
  "stages": [
    {
      "stage": 0,
      "component": [
        {"id": "c0", "name": "preflight_check", "cmd": "start", "prev": null}
      ]
    }
  ]
}
```

该模块继续保证：

- 本地 id 稳定递增。
- 未启用失败策略链时，每个 stage 一个 `ROBOT_CTRL`。
- 启用失败策略链后，同一 stage 可以有多个 `ROBOT_CTRL`，但这些 `ROBOT_CTRL` 的 `prev` 条件必须互斥。
- stage 内 SVR 与其服务的分支 `ROBOT_CTRL` 共享同一个 `prev` 条件。
- 主控制链沿 ROBOT_CTRL 的 `success` 串行推进；失败策略链沿指定组件的 `failed` 事件进入。

失败分支示例：

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
        {"id": "c3", "name": "return_home", "cmd": "start", "prev": "c1.failed"}
      ]
    }
  ]
}
```

这个结构中，`waypoint_flight` 和 `return_home` 虽然都在 stage 2，但它们分别由 `takeoff.success` 和 `takeoff.failed` 触发，运行时不会同时启动。

### 4.6 失败策略链规划器

失败策略链不应打断主链生成。推荐顺序是：

```text
main robot chain
  -> resolve main robot components
  -> attach optional failure strategy branches
  -> resolve branch services
  -> assemble guarded stages
```

设计原则：

- 失败策略链是可选分支，不是每个 `ROBOT_CTRL` 都必须拥有。
- 失败策略链的入口只能来自 `ROBOT_CTRL.failed`。
- 失败策略链可以是短链，例如 `A.failed -> return_home -> land`。
- 失败策略链也可以是恢复链，例如 `A.failed -> hover -> retry_navigation`，但 retry 类规则需要后续明确。
- 第一版建议只支持安全收束策略，优先生成返航、降落、悬停等保守动作。
- 失败策略链中的 `ROBOT_CTRL` 仍然必须来自组件库，并满足角色约束。
- 失败策略链可以复用主链已经启动的 SVR；若需要额外 SVR，应在该失败分支首次使用处按相同 `prev` 条件启动。
- 若主链和失败链都需要同一个 SVR，优先把该 SVR 提前到共同前驱 stage 启动，避免在静态拓扑中重复出现同名 SVR。

建议新增配置：

```json
{
  "failure_strategy_rules": {
    "enabled": false,
    "default_policy": "none",
    "policies": {
      "safe_return": {
        "trigger_roles": ["navigation.path", "navigation.point", "navigation.obstacle_avoid"],
        "on_failed": ["flight.return", "flight.land"],
        "selection_weight": 1.0
      },
      "safe_land": {
        "trigger_roles": ["flight.takeoff", "flight.altitude_up"],
        "on_failed": ["flight.land"],
        "selection_weight": 0.5
      },
      "hold_position": {
        "trigger_roles": ["tracking.target", "observation.hover"],
        "on_failed": ["observation.hover", "flight.return", "flight.land"],
        "selection_weight": 0.5
      }
    }
  }
}
```

内部数据结构建议从线性链升级为控制图：

```text
ControlNode:
  id
  role
  component_id
  branch_kind: main | failure

ControlEdge:
  source_node_id
  event: success | failed
  target_node_id
```

stage 由控制图拓扑层生成，而不是由简单 list 下标生成。装配时要给每个节点计算 `path_guard`：

```text
main branch:
  A.success -> B

failure branch:
  A.failed -> C
```

如果两个 `ROBOT_CTRL` 的 `path_guard` 互斥，它们可以放在同一个 stage。最小实现可以先只允许同一前驱节点的 `success` / `failed` 两个分支同 stage；后续再支持跨多级分支的互斥性传播。

### 4.7 校验器重构

校验器应分成三层。

第一层：结构校验，不依赖业务语义。

- 样本字段完整。
- stage 连续。
- 未启用失败策略链时，每个 stage 有且只有一个 `ROBOT_CTRL` start。
- 启用失败策略链后，同一 stage 可有多个 `ROBOT_CTRL` start，但它们的 `prev` 条件必须互斥，且任意运行路径上同一 stage 最多命中一个 `ROBOT_CTRL`。
- 所有组件必须存在于组件库。
- `prev` 只能引用已出现的 `ROBOT_CTRL`。
- `prev` 事件只能是 `success` 或 `failed`。
- SVR 不重复启动。
- 不允许组件参数和 UUID。

第二层：语义覆盖校验，基于角色而不是组件名。

- fixed-point 任务必须覆盖点位导航角色。
- line/area 任务必须覆盖路径或区域导航角色。
- object_detection 必须覆盖可见光采集和目标检测服务角色。
- target_tracking 必须覆盖检测服务和跟踪控制角色。
- obstacle_avoidance 必须覆盖避障导航角色和雷达服务角色。
- 高度为 medium/high 时必须覆盖高度上升角色。
- 高度为 high 时必须覆盖高度下降角色。
- return_home 为 true 时必须覆盖返航和降落角色。
- 启用失败策略链时，每条失败分支必须覆盖一个明确的失败处理角色序列，例如返航、降落或悬停。

校验器可以复用角色规划器来得到“预期角色集合”，但不应再复制具体组件链逻辑。具体组件是否合法由“组件是否拥有对应角色”判断。

第三层：控制图安全校验，专门服务失败策略链。

- 每条 `failed` 边必须来自 `ROBOT_CTRL`。
- 同一 stage 内多个 `ROBOT_CTRL` 的触发条件必须互斥。
- 失败分支不能重新汇入主链，除非配置显式声明 merge 策略。
- 失败分支不能产生无终止的循环。
- 失败分支的尾部必须进入安全终态，例如 `flight.return` + `flight.land` 或 `flight.land`。
- SVR 仍不能作为控制流前驱。

### 4.8 配置自检器

新增 `generator/config_linter.py`，用于在生成前检查配置质量。

必须检查：

- 每个模板引用的角色至少有一个启用组件。
- 每个角色候选组件的类型符合要求。
- 每个组件 id 唯一。
- 每个组件 type 只能是 `ROBOT_CTRL` 或 `SVR`。
- 每个 `ROBOT_CTRL` 至少有 `success`/`failed` 控制输出。
- 每个 SVR 不声明控制输出。
- 每个 topic provider 唯一或存在明确选择策略。
- 每个 required service role 能解析到 SVR。
- 每个 payload 支持的 capability 能解析到服务或控制角色。
- 每个 failure policy 的 trigger role 和 on_failed role 都能解析到合法 `ROBOT_CTRL`。
- failure policy 不允许引用 deferred 组件，除非该策略显式启用该组件。
- deferred 组件不会被默认规则选中。

配置自检应该在 pipeline 开始前运行，失败时直接停止生成。

## 5. 提高样本多样性的设计

重构不是只为降低耦合，还要为多样性留接口。

### 5.1 角色候选多样性

同一角色允许多个候选组件：

```json
{
  "role": "navigation.path",
  "candidates": [
    {"component": "waypoint_flight", "weight": 1.0}
  ]
}
```

当前只有一个候选时，结果不变。后续新增组件时，无需修改生成器。

### 5.2 拓扑变体多样性

对同一语义任务允许多个合法角色链，例如：

- 高度调整是否拆成 `ascend` / `descend`。
- 固定点任务是否包含 `hover`。
- 目标跟踪前是否增加观测稳定阶段。
- SVR 插入在 first-consumer stage 或 previous stage。
- 部分关键 `ROBOT_CTRL` 是否添加失败策略链。

这些变体必须通过配置声明，并带有条件和权重。

### 5.3 分布约束

新增分布控制目标：

```json
{
  "coverage_targets": {
    "task_type": "balanced",
    "route_mode": "balanced",
    "payload": "balanced",
    "robot_ctrl_component": "avoid_extreme_skew",
    "stage_count": "spread"
  }
}
```

pipeline 在生成后报告：

- 组件覆盖率。
- ROBOT_CTRL 覆盖率。
- SVR 覆盖率。
- stage_count 分布。
- action_count 分布。
- 拓扑 hash 重复率。
- 语义输入 hash 重复率。

### 5.4 稳定性保护

多样性不能牺牲稳定性。必须保留：

- 固定 seed 可复现。
- 失败样本直接过滤。
- 配置错误提前失败。
- 每次重构后对比基线报告。
- 默认策略保守，新增随机性必须有权重和上限。

## 6. 分阶段实施计划

### Phase 0：建立基线

目标：记录当前版本行为，作为重构回归基准。

任务：

- 固定命令：

  ```powershell
  $env:UV_CACHE_DIR = ".uv-cache"
  $env:PYTHONDONTWRITEBYTECODE = "1"
  uv run python -B -m generator.pipeline --count 100 --seed 42 --val-ratio 0.2
  ```

- 保存当前报告：
  - `stats/pipeline_report.json`
  - `stats/distribution_report.json`
  - `stats/validation_report.json`
- 记录当前关键指标：
  - generated_count
  - valid_count
  - invalid_count
  - duplicate_count
  - by_task_type
  - by_payload
  - by_route_mode
  - by_stage_count
  - by_action_count
  - by_component

验收：

- 当前基线为 100 生成、100 合法、0 无效、0 重复。

### Phase 1：组件语义标注

目标：补齐组件角色信息，但暂不改变生成逻辑。

任务：

- 更新 `config/component_library.json`，增加：
  - `roles`
  - `provides_topics`
  - `consumes_topics`
  - `lifecycle`
  - `selection_weight`
  - `enabled`
  - `status`
- 基于现有 `input_channels` / `output_channels` 自动或手动同步 topic 字段。
- 标注 `rotate` 和 `gimbal_control` 为 deferred。
- 新增 `generator/component_index.py`：
  - 构建 component_id 索引。
  - 构建 role -> components 索引。
  - 构建 topic -> providers 索引。
  - 构建 component -> consumed topics 索引。
- 新增 `generator/config_linter.py`。

验收：

- pipeline 输出保持不变或核心统计无明显变化。
- config linter 通过。
- 不改变 `target_topology` schema。

### Phase 2：抽象角色计划

目标：把任务模板从组件链迁移到角色链。

任务：

- 在配置中新增 `route_to_roles`，替代或并行保留 `route_to_robot_ctrl`：

  ```json
  {
    "goto_point": ["navigation.point"],
    "hover": ["navigation.point", "observation.hover"],
    "waypoint": ["navigation.path"],
    "grid": ["navigation.area"],
    "lawnmower": ["navigation.area"],
    "line_follow": ["navigation.line"]
  }
  ```

- 将高度、返航、降落、跟踪、避障规则改成角色规则：
  - `flight.altitude_up`
  - `flight.altitude_down`
  - `flight.return`
  - `flight.land`
  - `tracking.target`
  - `navigation.obstacle_avoid`
- 新增 `generator/planner.py`：
  - 输入 semantic_input。
  - 输出 abstract robot role chain。
  - 不直接输出组件名。

验收：

- 角色链能覆盖当前所有样本。
- 角色链解析成当前组件后，生成结果与 Phase 0 基本一致。

### Phase 3：角色解析与组件装配

目标：让生成器通过角色解析具体组件。

任务：

- 新增 `generator/role_resolver.py`：
  - 根据 role 选择组件。
  - 支持单候选确定性选择。
  - 支持未来多候选 weighted choice。
- 修改 `template_generator.py`：
  - `build_robot_ctrl_chain()` 改为：

    ```text
    build_abstract_plan()
      -> resolve_robot_roles()
      -> resolved_robot_chain
    ```

  - 移除直接写死的 `preflight_check`、`takeoff`、`return_home`、`land`。
- 保留 `build_topology()` 的现有行为。

验收：

- 100 条样本全部通过。
- 生成结果仍满足每 stage 一个 ROBOT_CTRL。
- `ascend` / `descend` 逻辑保持。
- `rotate` 不被默认引入。

### Phase 4：SVR 依赖解析重构

目标：替换 `_first_consumer_stage()` 和部分硬编码 SVR 映射。

任务：

- 新增 `generator/service_resolver.py`。
- 根据 capability 先加入显式服务角色。
- 根据已选组件的 `consumes_topics` 做 topic 闭包解析。
- 将服务角色解析成 SVR 组件。
- 计算每个 SVR 的插入 stage：
  - 找到第一个消费该 SVR 输出 topic 的 ROBOT_CTRL。
  - 找不到消费者但属于全局服务时，插入 stage 0。
  - 找不到消费者且不是全局服务时，报配置警告或校验错误。
- 删除或废弃 `_first_consumer_stage()`。

验收：

- `waypoint_flight` 自动引入 `waypoint_list_create`。
- `goto_point` / `obstacle_avoid_flight` 自动引入定位服务。
- `object_detect` 自动引入 `sensor_camera_scan`。
- `target_tracking` 自动引入检测服务。
- `battery_level` / `battery_warning` 仍能作为显式安全服务加入。
- 不产生 SVR-only stage。

### Phase 5：校验器角色化

目标：降低 validator 与具体组件名的耦合。

任务：

- 保留结构校验逻辑。
- 将语义一致性校验改为角色覆盖校验。
- 删除或弱化：
  - `_expected_robot_ctrl_chain()`
  - `_expected_svr_services()`
  - `_validate_required_component_presence()` 中的组件名集合判断。
- 新增：
  - `_validate_required_roles_present()`
  - `_validate_required_service_roles_present()`
  - `_validate_topic_dependencies_satisfied()`
- validator 通过组件 roles 判断是否满足语义需求。

验收：

- 现有 100 条样本继续全部合法。
- 手动构造缺失关键角色的样本能被拒绝。
- 手动构造未知组件、SVR 作为 prev、重复 SVR 的样本能被拒绝。

### Phase 6：失败策略链支持

目标：在主控制链生成稳定后，支持可选的失败处理分支。

任务：

- 新增 `generator/failure_strategy.py` 或并入 `planner.py`：
  - 根据配置选择哪些主链节点需要失败策略。
  - 根据节点角色选择失败处理角色链。
  - 将 `A.failed -> C` 分支追加到控制图。
- 将内部结构从纯 `robot_ctrl_chain` 升级为 `control_graph`。
- Stage 装配器支持 guarded stage：
  - `A.success -> B`
  - `A.failed -> C`
  - `B` 和 `C` 可位于同一 stage，因为触发条件互斥。
- 服务解析器支持分支级 SVR：
  - 主链和失败链共享已提前启动的 SVR。
  - 失败链独有 SVR 按失败分支 `prev` 条件启动。
- validator 增加互斥条件校验和失败分支终态校验。
- pipeline 报告增加：
  - `by_failure_policy`
  - `failure_branch_count`
  - `guarded_robot_ctrl_stage_count`

第一版约束：

- 默认关闭失败策略链，避免影响 Phase 0 基线。
- 只支持从 `ROBOT_CTRL.failed` 出发。
- 只支持安全收束策略，不支持复杂 retry 和 merge。
- 失败分支不回流主链。
- 同一主链节点最多挂载一条失败策略链。

验收：

- 未启用失败策略链时，生成结果与 Phase 0/Phase 5 保持一致。
- 启用失败策略链后，所有样本仍通过结构校验。
- 手动构造 `A.success -> B` 与 `A.failed -> C` 的样本能被判定合法。
- 手动构造同一 stage 两个 `ROBOT_CTRL` 使用相同 `prev` 条件的样本能被拒绝。
- 手动构造失败分支无安全终态的样本能被拒绝。
- 任意运行路径上仍满足同一时刻只有一个 `ROBOT_CTRL`。

### Phase 7：多样性策略开放

目标：在稳定架构上逐步提高样本多样性。

任务：

- 支持角色多候选组件选择。
- 支持拓扑变体规则：
  - 可选 hover。
  - 可选高度调整。
  - 可选 SVR 提前启动。
  - 可选观测稳定阶段。
  - 可选失败策略链。
- 增加拓扑去重 hash：
  - 只看组件序列。
  - 看 stage/action 结构。
  - 看 semantic_input + topology。
- 增加分布控制：
  - task_type 均衡。
  - route_mode 均衡。
  - payload 均衡。
  - stage_count 覆盖。
  - component 覆盖。

验收：

- valid_rate 保持 1.0 或接近 1.0。
- duplicate_count 不上升。
- stage_count 和 action_count 分布更分散。
- 未使用组件数下降，但不能为了覆盖强行加入语义不清组件。

## 7. 风险与应对

| 风险 | 说明 | 应对 |
| --- | --- | --- |
| topic 信息不完整 | 自动依赖推导依赖组件输入输出 topic，组件库不准会导致漏插或误插 SVR | 增加 config linter；保留显式 service role 规则作为兜底 |
| 生成分布漂移 | 多候选和权重会改变样本分布 | 第一阶段只做等价迁移；后续每次开放多样性都对比基线 |
| validator 与 generator 过度复用 | 完全复用同一逻辑可能掩盖生成器错误 | 结构校验独立；语义校验基于角色覆盖和 topic 依赖，而不是复制组件链 |
| `rotate` 语义不清 | 直接插入 rotate 可能生成不合理飞控链 | 继续 deferred，等语义输入中出现航向调整或环视扫描需求再启用 |
| `gimbal_control` 无输出 topic | topic 推导无法自动判断其价值 | 需要显式语义触发，例如 `gimbal_required` 或 `target_recenter` |
| 配置复杂度上升 | roles、weights、policies 会增加配置维护成本 | 通过 config linter、文档和小步迁移控制复杂度 |

## 8. 推荐文件结构

建议新增或调整为：

```text
config/
  component_library.json
  params_space.json
  task_types.json
  task_templates.py
  generation_rules.json        # 可选：后续把 Python 规则迁出

generator/
  component_index.py           # 组件、角色、topic 索引
  config_linter.py             # 配置自检
  planner.py                   # semantic_input -> abstract plan
  role_resolver.py             # role -> component
  service_resolver.py          # service/topic dependency resolution
  control_graph.py             # 控制图节点、边、互斥 guard 计算
  failure_strategy.py          # 可选失败策略链生成
  template_generator.py        # 对外生成入口和拓扑装配
  validator.py                 # 结构校验 + 角色覆盖校验
  pipeline.py
```

如果希望减少文件数量，也可以先把 `planner.py`、`role_resolver.py`、`service_resolver.py`、`failure_strategy.py` 合并到一个 `generator/planning.py`，等逻辑稳定后再拆分。

## 9. 验收指标

### 9.1 功能指标

每个阶段完成后运行：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:PYTHONDONTWRITEBYTECODE = "1"
uv run python -B -m generator.pipeline --count 100 --seed 42 --val-ratio 0.2
```

必须满足：

```text
generated_count = 100
valid_count = 100
invalid_count = 0
duplicate_count = 0
train_count = 80
val_count = 20
```

### 9.2 结构指标

必须持续满足：

- 未启用失败策略链时，每个 stage 有且只有一个 `ROBOT_CTRL`。
- 启用失败策略链时，同一 stage 内多个 `ROBOT_CTRL` 必须处于互斥 `prev` 条件下。
- 任意运行路径上，同一 stage 最多启动一个 `ROBOT_CTRL`。
- 不存在 SVR-only stage。
- SVR 不作为 `prev` 来源。
- SVR 不重复启动。
- 输出不包含组件参数。
- 输出不包含 UUID。

### 9.3 多样性指标

重构完成后重点观察：

- `by_stage_count` 分布是否更分散。
- `by_action_count` 分布是否更分散。
- `by_component` 覆盖是否提高。
- 拓扑 hash 重复率是否下降。
- 未使用组件是否减少。
- 启用失败策略链后，`failure_branch_count` 和 `by_failure_policy` 是否符合预期。

注意：`rotate` 和 `gimbal_control` 只有在语义触发明确后才应纳入覆盖目标。

## 10. 建议执行顺序

最稳妥的执行顺序是：

1. 建立基线报告。
2. 增加组件 roles/topic/lifecycle 标注。
3. 实现 `component_index.py` 和 `config_linter.py`。
4. 新增 abstract planner，但先不替换旧生成器。
5. 用 abstract planner 生成与旧逻辑等价的组件链。
6. 替换 `template_generator.py` 的硬编码链路。
7. 重构 SVR 依赖解析。
8. 重构 validator 为角色覆盖校验。
9. 增加可选失败策略链，但默认保持关闭。
10. 开放多候选和拓扑变体。
11. 更新 README 和 TASKS。

## 11. 最小可行重构范围

如果希望先做最小改动，建议只做以下四件事：

1. 给组件库添加 `roles` 和 `enabled`。
2. 新增 `component_index.py` 和 `config_linter.py`。
3. 把基础飞控链从代码迁移到角色配置。
4. validator 改为校验角色覆盖，而不是硬编码组件集合。

这四步完成后，组件变更带来的代码改动会明显减少；之后再处理 topic 自动依赖和多样性策略。

失败策略链不建议纳入最小可行重构范围。它依赖控制图、互斥 guard 校验和分支级服务解析，应该在角色化生成和角色化校验稳定之后再启用。

## 12. 最终判断

该重构方案可行，且符合当前项目目标。

短期收益：

- 降低组件变动导致的大面积代码修改。
- 消除生成器和校验器之间的重复业务规则。
- 让配置错误更早暴露。

中期收益：

- 支持同一语义角色下的多组件候选。
- 支持更自然的拓扑变体。
- 支持在主控制链之外追加可选失败策略链。
- 提升样本多样性并降低重复率。

长期收益：

- 支持真实平台组件库持续演化。
- 支持 LLM 正向/反向扩充前的高质量模板种子生成。
- 支持后续把拓扑生成、参数填充、执行编译拆成更清晰的流水线。

建议下一步先执行 Phase 1，不直接大改生成逻辑。这样可以先把组件语义层和配置自检打牢，再逐步替换核心生成逻辑。
